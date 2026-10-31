from django.db.models import Q

from core.identity import eligible
from core.models import Membership, User
from tickets.models import Comment, ReadGrant, Ticket


def support_memberships(user):
    if user.role not in {User.Role.TECHNICIAN, User.Role.MANAGER}:
        return Membership.objects.none()
    return Membership.objects.filter(user=user, group__is_active=True)


def visible_tickets(user):
    if not user.is_authenticated or not eligible(user):
        return Ticket.objects.none()
    memberships = support_memberships(user)
    scope = Q(requester=user)
    scope |= Q(group_id__in=memberships.values("group_id"), restricted=False)
    scope |= Q(group_id__in=memberships.filter(can_view_restricted=True).values("group_id"))
    if user.role in {User.Role.ADMIN, User.Role.PRIVACY}:
        grants = ReadGrant.objects.filter(user=user, group__is_active=True)
        scope |= Q(group_id__in=grants.values("group_id"), restricted=False)
        scope |= Q(group_id__in=grants.filter(restricted=True).values("group_id"))
    return Ticket.objects.filter(scope)


def membership(user, ticket):
    if ticket.requester_id == user.pk:
        return None  # A technician requesting help acts as requester on their own ticket.
    memberships = support_memberships(user).filter(group_id=ticket.group_id)
    if ticket.restricted:
        memberships = memberships.filter(can_view_restricted=True)
    return memberships.first()


def can_read_internal(user, ticket):
    if ticket.requester_id == user.pk:
        return False
    if membership(user, ticket):
        return True
    if user.role not in {User.Role.ADMIN, User.Role.PRIVACY}:
        return False
    grants = ReadGrant.objects.filter(
        user=user, group_id=ticket.group_id, group__is_active=True, internal=True
    )
    return grants.filter(restricted=True).exists() if ticket.restricted else grants.exists()


def visible_history(queryset, user, ticket):
    return (
        queryset
        if can_read_internal(user, ticket)
        else queryset.filter(visibility=Comment.Visibility.PUBLIC)
    )


def outbox_projection(outbox, recipient):
    """Stage-5 handoff: authorization is checked at use time, not trusted from queued data."""
    recipient = User.objects.get(pk=recipient.pk)
    event = outbox.event
    ticket = visible_tickets(recipient).filter(pk=event.ticket_id).first()
    if not ticket or (
        event.visibility == Comment.Visibility.INTERNAL and not can_read_internal(recipient, ticket)
    ):
        return None
    return {
        "ticket_id": str(ticket.uuid),
        "number": ticket.number,
        "state": ticket.state,
        "event_id": str(event.pk),
    }
