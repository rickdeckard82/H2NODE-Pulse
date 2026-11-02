import hashlib
import json
import uuid
from datetime import timedelta

from django.db import connection, transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError

from core.identity import eligible
from core.identity_views import locked_actor
from core.models import Membership, SupportGroup, User
from tickets.models import (
    AuditEvent,
    Category,
    Comment,
    IdempotencyRecord,
    NotificationOutbox,
    ReopenPolicy,
    SlaPolicy,
    Ticket,
    TicketEvent,
)
from tickets.permissions import can_read_internal, membership, visible_tickets


class Conflict(APIException):
    status_code = 409
    default_detail = "O chamado mudou. Atualize os dados antes de tentar novamente."
    default_code = "conflict"


def key_from_request(request):
    try:
        return uuid.UUID(request.headers.get("Idempotency-Key", ""))
    except ValueError:
        raise ValidationError({"Idempotency-Key": "Informe uma chave UUID por operação."}) from None


def emit(ticket, actor, action, previous, comment=None, changes=None, visibility=None):
    now = timezone.now()
    event = TicketEvent.objects.create(
        ticket=ticket,
        actor=actor,
        action=action,
        version=ticket.version,
        visibility=visibility or (comment.visibility if comment else Comment.Visibility.PUBLIC),
        from_state=previous,
        to_state=ticket.state,
        comment=comment,
        changes=changes or {},
        created_at=now,
    )
    AuditEvent.objects.create(
        event=event,
        actor=actor,
        action=action,
        created_at=now,
        correlation_id=event.correlation_id,
        changes={
            **event.changes,
            "ticket_id": str(ticket.uuid),
            "version": ticket.version,
            "from_state": previous,
            "to_state": ticket.state,
            "comment_id": str(comment.pk) if comment else None,
        },
    )
    NotificationOutbox.objects.create(
        event=event,
        created_at=now,
        audience="support"
        if event.visibility == Comment.Visibility.INTERNAL
        else "requester_and_support",
        payload={
            "ticket_id": str(ticket.uuid),
            "event_id": str(event.pk),
            "visibility": event.visibility,
        },
    )
    return event


def advance(ticket):
    ticket.version += 1
    ticket.updated_at = timezone.now()
    ticket.save()


@transaction.atomic
def execute(request, operation, payload, mutation, ticket_uuid=None, status_code=200):
    """Permission changes serialize against mutations, but independent tickets can run together."""
    key = key_from_request(request)
    scope = f"ticket:{ticket_uuid or 'new'}:{operation}"
    fingerprint = hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode()
    ).hexdigest()
    lock_value = int.from_bytes(
        hashlib.blake2b(f"{request.user.pk}:{scope}:{key}".encode(), digest_size=8).digest(),
        signed=True,
    )
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock_shared(721984021)")
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [lock_value])
    actor = locked_actor(request, no_key=True)
    record = IdempotencyRecord.objects.filter(user=actor, operation=scope, key=key).first()
    if record:
        ticket = get_object_or_404(visible_tickets(actor), pk=record.event.ticket_id)
        if record.event.visibility == Comment.Visibility.INTERNAL and not can_read_internal(
            actor, ticket
        ):
            raise PermissionDenied("Sem acesso ao evento.")
        if record.payload_hash != fingerprint:
            raise Conflict("Chave de idempotência já utilizada com dados diferentes.")
        return record.response, record.status_code, True
    ticket = None
    if ticket_uuid:
        ticket = get_object_or_404(
            visible_tickets(actor).select_for_update(of=("self",)), uuid=ticket_uuid
        )
        if ticket.version != payload["expected_version"]:
            raise Conflict()
    event = mutation(actor, ticket, payload)
    ticket = event.ticket
    result = {
        "ticket_id": str(ticket.uuid),
        "number": ticket.number,
        "event_id": str(event.pk),
        "version": event.version,
        "state": ticket.state,
        "correlation_id": str(event.correlation_id),
    }
    IdempotencyRecord.objects.create(
        user=actor,
        operation=scope,
        key=key,
        payload_hash=fingerprint,
        event=event,
        response=result,
        status_code=status_code,
    )
    return result, status_code, False


def create_ticket(actor, unused, data):
    category = get_object_or_404(
        Category, pk=data["category"], is_active=True, group__is_active=True
    )
    related = None
    if data.get("related_ticket"):
        related = get_object_or_404(
            visible_tickets(actor), uuid=data["related_ticket"], requester=actor
        )
        if related.restricted and not category.restricted:
            raise ValidationError(
                "Um chamado vinculado a conteúdo restrito deve continuar restrito."
            )
    score = data["impact"] + data["urgency"]
    ticket = Ticket.objects.create(
        requester=actor,
        department=actor.department,
        department_name=actor.department.name if actor.department_id else "",
        category=category,
        group=category.group,
        restricted=category.restricted,
        subject=data["subject"],
        description=data["description"],
        impact=data["impact"],
        urgency=data["urgency"],
        priority={6: 1, 5: 2, 4: 3, 3: 4, 2: 4}[score],
        reopen_policy=ReopenPolicy.objects.order_by("-pk").first(),
        sla_policy=SlaPolicy.objects.order_by("-pk").first(),
        related_ticket=related,
    )
    return emit(
        ticket,
        actor,
        "created",
        "",
        changes={
            "group": ticket.group_id,
            "priority": ticket.priority,
            "restricted": ticket.restricted,
        },
    )


def require_support(actor, ticket, assigned=False):
    member = membership(actor, ticket)
    if not member or (
        assigned
        and ticket.assignee_id != actor.pk
        and not ticket.participants.filter(pk=actor.pk).exists()
    ):
        raise PermissionDenied("Ação exige técnico autorizado e, quando aplicável, atribuído.")
    return member


def valid_assignee(user, group, restricted, requester_id):
    if (
        not eligible(user)
        or user.pk == requester_id
        or user.role not in {User.Role.TECHNICIAN, User.Role.MANAGER}
    ):
        return False
    if not group.is_active:
        return False
    members = Membership.objects.filter(user=user, group=group, can_view_restricted=True)
    return members.exists() if restricted else True


def check_assignment(ticket):
    if not ticket.assignee_id or not valid_assignee(
        ticket.assignee, ticket.group, ticket.restricted, ticket.requester_id
    ):
        raise Conflict("A TI precisa regularizar a atribuição antes desta ação.")


def claim(actor, ticket, data):
    require_support(actor, ticket)
    if ticket.state != Ticket.State.NEW or ticket.assignee_id:
        raise Conflict("O chamado já foi assumido ou saiu da fila de novos.")
    before = ticket.state
    ticket.assignee, ticket.state = actor, Ticket.State.ACTIVE
    advance(ticket)
    return emit(ticket, actor, "claimed", before, changes={"assignee": actor.pk})


def join(actor, ticket, data):
    require_support(actor, ticket)
    if ticket.state not in {Ticket.State.ACTIVE, Ticket.State.INFORMATION, Ticket.State.TEST}:
        raise Conflict("Só é possível participar de chamados em atendimento.")
    if ticket.assignee_id == actor.pk or ticket.participants.filter(pk=actor.pk).exists():
        raise Conflict("Você já participa deste chamado.")
    ticket.participants.add(actor)
    advance(ticket)
    return emit(
        ticket, actor, "participant.joined", ticket.state, changes={"participant": actor.pk}
    )


def add_comment(actor, ticket, data):
    visibility = data["visibility"]
    owner = ticket.requester_id == actor.pk
    if visibility == Comment.Visibility.INTERNAL:
        require_support(actor, ticket)
    elif not owner:
        require_support(actor, ticket)
    correction = None
    if data.get("corrects"):
        correction = get_object_or_404(
            Comment, pk=data["corrects"], ticket=ticket, actor=actor, visibility=visibility
        )
    if ticket.state in {Ticket.State.CLOSED, Ticket.State.CANCELLED} and not correction:
        raise Conflict("Chamado encerrado; utilize a ação de reabertura quando permitida.")
    before = ticket.state
    action = "comment.corrected" if correction else "comment.added"
    if owner and not correction and ticket.state in {Ticket.State.INFORMATION, Ticket.State.TEST}:
        check_assignment(ticket)
        ticket.state, action = Ticket.State.ACTIVE, "requester.replied"
    comment = Comment.objects.create(
        ticket=ticket, actor=actor, body=data["body"], visibility=visibility, corrects=correction
    )
    advance(ticket)
    return emit(ticket, actor, action, before, comment=comment)


def transition(actor, ticket, data):
    action, before = data["action"], ticket.state
    owner = ticket.requester_id == actor.pk
    member = membership(actor, ticket)
    manager = bool(member and actor.role == User.Role.MANAGER)
    body = data.get("message", "")
    text_actions = {
        "request_information",
        "request_test",
        "resolve",
        "reopen",
        "cancel",
        "return_queue",
        "close",
    }
    if action in text_actions and not body:
        raise ValidationError({"message": "Informe o texto público obrigatório para esta ação."})
    if data.get("assignee") and not (action == "reopen" and manager):
        raise ValidationError(
            {"assignee": "Apenas o gestor pode regularizar a atribuição na reabertura."}
        )
    if data.get("resolution_class") and action != "resolve":
        raise ValidationError({"resolution_class": "Campo exclusivo da resolução."})
    if action in {"request_information", "request_test", "resolve"}:
        require_support(actor, ticket, assigned=True)
        if before != Ticket.State.ACTIVE:
            raise Conflict("Esta ação exige chamado em atendimento.")
        if action == "resolve":
            if not data.get("resolution_class"):
                raise ValidationError({"resolution_class": "Informe a classificação da solução."})
            ticket.state, ticket.resolved_at = Ticket.State.RESOLVED, timezone.now()
            ticket.resolution_class = data["resolution_class"]
        else:
            ticket.state = (
                Ticket.State.INFORMATION if action == "request_information" else Ticket.State.TEST
            )
    elif action == "confirm":
        if not owner:
            raise PermissionDenied("Somente o solicitante pode confirmar a solução.")
        if before != Ticket.State.RESOLVED:
            raise Conflict("Somente chamados resolvidos podem ser confirmados.")
        ticket.state, ticket.closed_at = Ticket.State.CLOSED, timezone.now()
    elif action == "close":
        if not owner:
            raise PermissionDenied("Somente o solicitante pode encerrar o chamado.")
        if before not in {
            Ticket.State.ACTIVE,
            Ticket.State.INFORMATION,
            Ticket.State.TEST,
            Ticket.State.RESOLVED,
        }:
            raise Conflict("Chamado novo deve ser cancelado; encerrados não mudam.")
        ticket.state, ticket.closed_at = Ticket.State.CLOSED, timezone.now()
    elif action == "reopen":
        if not owner and not (manager and before == Ticket.State.CLOSED):
            raise PermissionDenied("Reabertura não autorizada.")
        if before not in {Ticket.State.RESOLVED, Ticket.State.CLOSED}:
            raise Conflict("O chamado não está resolvido ou fechado.")
        if before == Ticket.State.CLOSED:
            policy = ticket.reopen_policy
            if (
                not policy
                or policy.hours == 0
                or not ticket.closed_at
                or timezone.now() > ticket.closed_at + timedelta(hours=policy.hours)
            ):
                raise Conflict("Fora da janela de reabertura. Abra um novo chamado vinculado.")
        if data.get("assignee"):
            user = get_object_or_404(User, pk=data["assignee"])
            if not valid_assignee(user, ticket.group, ticket.restricted, ticket.requester_id):
                raise ValidationError({"assignee": "Técnico indisponível para este chamado."})
            ticket.assignee = user
        check_assignment(ticket)
        ticket.state = Ticket.State.ACTIVE
    elif action == "cancel":
        if not ((owner and before == Ticket.State.NEW) or (manager and member.can_cancel)):
            raise PermissionDenied("Cancelamento não autorizado.")
        if before in {Ticket.State.CLOSED, Ticket.State.CANCELLED}:
            raise Conflict("Chamado já encerrado.")
        ticket.state = Ticket.State.CANCELLED
    elif action == "return_queue":
        require_support(actor, ticket)
        if not member.can_transfer:
            raise PermissionDenied("Sem permissão de transferência.")
        if before in {Ticket.State.NEW, Ticket.State.CLOSED, Ticket.State.CANCELLED}:
            raise Conflict("Não é possível devolver este estado à fila.")
        ticket.state, ticket.assignee = Ticket.State.NEW, None
        ticket.participants.clear()
    else:
        raise ValidationError({"action": "Ação desconhecida."})
    comment = (
        Comment.objects.create(
            ticket=ticket, actor=actor, body=body, visibility=Comment.Visibility.PUBLIC
        )
        if body
        else None
    )
    advance(ticket)
    return emit(
        ticket,
        actor,
        action,
        before,
        comment=comment,
        changes={"assignee": ticket.assignee_id, "resolution_class": ticket.resolution_class},
    )


def transfer(actor, ticket, data):
    member = require_support(actor, ticket)
    if not member.can_transfer:
        raise PermissionDenied("Sem permissão de transferência.")
    if ticket.state in {Ticket.State.CLOSED, Ticket.State.CANCELLED}:
        raise Conflict("Não é possível transferir chamado encerrado.")
    group = get_object_or_404(SupportGroup, pk=data["group"], is_active=True)
    destination = Membership.objects.filter(user=actor, group=group)
    if ticket.restricted:
        destination = destination.filter(can_view_restricted=True)
    if not destination.exists():
        raise PermissionDenied("Sem acesso ao grupo de destino.")
    assignee = get_object_or_404(User, pk=data["assignee"])
    if not valid_assignee(assignee, group, ticket.restricted, ticket.requester_id):
        raise ValidationError({"assignee": "Técnico indisponível no grupo de destino."})
    before = ticket.state
    changes = {
        "group": {"from": ticket.group_id, "to": group.pk},
        "assignee": {"from": ticket.assignee_id, "to": assignee.pk},
    }
    ticket.group, ticket.assignee = group, assignee
    if before == Ticket.State.NEW:
        ticket.state = Ticket.State.ACTIVE
    comment = Comment.objects.create(
        ticket=ticket, actor=actor, body=data["message"], visibility=Comment.Visibility.PUBLIC
    )
    advance(ticket)
    return emit(ticket, actor, "transferred", before, comment=comment, changes=changes)
