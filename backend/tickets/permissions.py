from django.db.models import Q

from core.identity import eligible
from core.models import Membership, User
from tickets.models import Comment, ReadGrant, Ticket


def support_memberships(user):
    if user.role not in {User.Role.TECHNICIAN, User.Role.MANAGER}:
        return Membership.objects.none()
    return Membership.objects.filter(user=user, group__is_active=True)


def group_scope(user):
    memberships = support_memberships(user)
    # Every technician sees the whole open queue; restricted tickets still need an explicit grant.
    scope = (
        Q(group__is_active=True, restricted=False)
        if user.role in {User.Role.TECHNICIAN, User.Role.MANAGER}
        else Q(pk__in=[])
    )
    scope |= Q(group_id__in=memberships.filter(can_view_restricted=True).values("group_id"))
    if user.role in {User.Role.ADMIN, User.Role.PRIVACY}:
        grants = ReadGrant.objects.filter(user=user, group__is_active=True)
        scope |= Q(group_id__in=grants.values("group_id"), restricted=False)
        scope |= Q(group_id__in=grants.filter(restricted=True).values("group_id"))
    return scope


def visible_tickets(user):
    if not user.is_authenticated or not eligible(user):
        return Ticket.objects.none()
    return Ticket.objects.filter(Q(requester=user) | group_scope(user))


def report_tickets(user):
    """Reports follow group scope only: being the requester never widens them."""
    if not eligible(user) or user.role not in {
        User.Role.MANAGER,
        User.Role.ADMIN,
        User.Role.PRIVACY,
    }:
        return Ticket.objects.none()
    return Ticket.objects.filter(group_scope(user))


def membership(user, ticket):
    if ticket.requester_id == user.pk:
        return None  # A technician requesting help acts as requester on their own ticket.
    memberships = support_memberships(user).filter(group_id=ticket.group_id)
    if ticket.restricted:
        return memberships.filter(can_view_restricted=True).first()
    if not ticket.group.is_active or user.role not in {User.Role.TECHNICIAN, User.Role.MANAGER}:
        return None
    # Outside their groups a technician supports the ticket without transfer/cancel rights.
    return memberships.first() or Membership(user=user, group=ticket.group)


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
