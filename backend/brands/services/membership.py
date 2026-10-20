from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from accounts.models import User
from brands.models import Brand, JoinRequest, Team, TeamInvitation, TeamMembership


def _require_agent(user: User) -> User:
    if user.role != User.Role.AGENT and not user.is_superuser:
        raise ValidationError("Only agents can join a team.")
    return user


def activate_membership(team: Team, agent: User) -> TeamMembership:
    membership, created = TeamMembership.objects.get_or_create(
        team=team,
        agent=agent,
        defaults={"status": TeamMembership.Status.ACTIVE, "joined_at": timezone.now()},
    )
    if not created and membership.status != TeamMembership.Status.ACTIVE:
        membership.status = TeamMembership.Status.ACTIVE
        membership.joined_at = timezone.now()
        membership.save(update_fields=["status", "joined_at", "updated_at"])
    return membership


def invite_agent(
    *,
    team: Team,
    agent: User,
    invited_by: User,
    expires_in_days: int = 14,
) -> TeamInvitation:
    _require_agent(agent)
    if TeamMembership.objects.filter(
        team=team, agent=agent, status=TeamMembership.Status.ACTIVE
    ).exists():
        raise ValidationError("This agent is already an active member of the team.")
    if TeamInvitation.objects.filter(
        team=team, agent=agent, status=TeamInvitation.Status.PENDING
    ).exists():
        raise ValidationError("A pending invitation already exists for this agent.")
    expires_at = timezone.now() + timedelta(days=expires_in_days) if expires_in_days else None
    return TeamInvitation.objects.create(
        team=team,
        agent=agent,
        invited_by=invited_by,
        expires_at=expires_at,
    )


def accept_invitation(invitation: TeamInvitation, *, agent: User | None = None) -> TeamMembership:
    if agent is not None and invitation.agent_id != agent.pk:
        raise ValidationError("This invitation belongs to a different agent.")
    invitation = TeamInvitation.objects.get(pk=invitation.pk)
    if invitation.status != TeamInvitation.Status.PENDING:
        raise ValidationError("This invitation is no longer pending.")
    if invitation.is_expired():
        invitation.status = TeamInvitation.Status.EXPIRED
        invitation.responded_at = timezone.now()
        invitation.save(update_fields=["status", "responded_at"])
        raise ValidationError("This invitation has expired.")
    with transaction.atomic():
        invitation = TeamInvitation.objects.select_for_update().get(pk=invitation.pk)
        if invitation.status != TeamInvitation.Status.PENDING:
            raise ValidationError("This invitation is no longer pending.")
        membership = activate_membership(invitation.team, invitation.agent)
        invitation.status = TeamInvitation.Status.ACCEPTED
        invitation.responded_at = timezone.now()
        invitation.save(update_fields=["status", "responded_at"])
        JoinRequest.objects.filter(
            team=invitation.team,
            agent=invitation.agent,
            status=JoinRequest.Status.PENDING,
        ).update(status=JoinRequest.Status.ACCEPTED, responded_at=timezone.now())
        return membership


def decline_invitation(invitation: TeamInvitation, *, agent: User | None = None) -> TeamInvitation:
    if agent is not None and invitation.agent_id != agent.pk:
        raise ValidationError("This invitation belongs to a different agent.")
    if invitation.status != TeamInvitation.Status.PENDING:
        raise ValidationError("This invitation is no longer pending.")
    invitation.status = TeamInvitation.Status.DECLINED
    invitation.responded_at = timezone.now()
    invitation.save(update_fields=["status", "responded_at"])
    return invitation


def cancel_invitation(invitation: TeamInvitation) -> TeamInvitation:
    if invitation.status != TeamInvitation.Status.PENDING:
        raise ValidationError("Only pending invitations can be cancelled.")
    invitation.status = TeamInvitation.Status.CANCELLED
    invitation.responded_at = timezone.now()
    invitation.save(update_fields=["status", "responded_at"])
    return invitation


def request_to_join_brand(
    *,
    brand,
    agent: User,
    message: str = "",
    team_id: int | None = None,
) -> JoinRequest:
    """Ask to represent a brand. Membership stays inactive until the owner approves."""
    if brand.status != Brand.Status.ACTIVE:
        raise ValidationError("This brand is not accepting agents.")
    _require_agent(agent)
    if TeamMembership.objects.filter(
        agent=agent,
        status=TeamMembership.Status.ACTIVE,
        team__brand=brand,
    ).exists():
        raise ValidationError("You already belong to a team for this brand.")
    if JoinRequest.objects.filter(
        agent=agent,
        status=JoinRequest.Status.PENDING,
        team__brand=brand,
    ).exists():
        raise ValidationError("A join request is already waiting for the brand owner.")
    active_teams = Team.objects.filter(brand=brand, status=Team.Status.ACTIVE).order_by("id")
    if team_id:
        team = active_teams.filter(pk=team_id).first()
        if team is None:
            raise ValidationError("Choose an active team for this brand.")
    elif active_teams.count() > 1:
        raise ValidationError("Choose a team to join.")
    elif active_teams.exists():
        team = active_teams.first()
    else:
        team, _created = Team.objects.get_or_create(
            brand=brand,
            name="Agents",
            defaults={
                "description": "Agents who asked to represent this brand.",
                "status": Team.Status.ACTIVE,
            },
        )
        if team.status != Team.Status.ACTIVE:
            team.status = Team.Status.ACTIVE
            team.save(update_fields=["status", "updated_at"])
    return create_join_request(team=team, agent=agent, message=message)


def create_join_request(*, team: Team, agent: User, message: str = "") -> JoinRequest:
    _require_agent(agent)
    if TeamMembership.objects.filter(
        team=team, agent=agent, status=TeamMembership.Status.ACTIVE
    ).exists():
        raise ValidationError("This agent is already an active member of the team.")
    if JoinRequest.objects.filter(
        team=team, agent=agent, status=JoinRequest.Status.PENDING
    ).exists():
        raise ValidationError("A pending join request already exists for this team.")
    request = JoinRequest(team=team, agent=agent, message=message)
    request.full_clean()
    request.save()
    return request


@transaction.atomic
def accept_join_request(join_request: JoinRequest, *, reviewed_by: User) -> TeamMembership:
    join_request = JoinRequest.objects.select_for_update().get(pk=join_request.pk)
    if join_request.status != JoinRequest.Status.PENDING:
        raise ValidationError("This join request is no longer pending.")
    membership = activate_membership(join_request.team, join_request.agent)
    join_request.status = JoinRequest.Status.ACCEPTED
    join_request.responded_at = timezone.now()
    join_request.reviewed_by = reviewed_by
    join_request.save(update_fields=["status", "responded_at", "reviewed_by"])
    TeamInvitation.objects.filter(
        team=join_request.team,
        agent=join_request.agent,
        status=TeamInvitation.Status.PENDING,
    ).update(status=TeamInvitation.Status.ACCEPTED, responded_at=timezone.now())
    return membership


def reject_join_request(join_request: JoinRequest, *, reviewed_by: User) -> JoinRequest:
    if join_request.status != JoinRequest.Status.PENDING:
        raise ValidationError("This join request is no longer pending.")
    join_request.status = JoinRequest.Status.REJECTED
    join_request.responded_at = timezone.now()
    join_request.reviewed_by = reviewed_by
    join_request.save(update_fields=["status", "responded_at", "reviewed_by"])
    return join_request


def cancel_join_request(join_request: JoinRequest, *, agent: User) -> JoinRequest:
    if join_request.agent_id != agent.pk:
        raise ValidationError("This join request belongs to a different agent.")
    if join_request.status != JoinRequest.Status.PENDING:
        raise ValidationError("This join request is no longer pending.")
    join_request.status = JoinRequest.Status.CANCELLED
    join_request.responded_at = timezone.now()
    join_request.save(update_fields=["status", "responded_at"])
    return join_request


def set_team_status(team: Team, status: str) -> Team:
    allowed = {Team.Status.ACTIVE, Team.Status.PAUSED, Team.Status.ARCHIVED}
    if status not in allowed:
        raise ValidationError("Invalid team status.")
    if team.status != status:
        team.status = status
        team.save(update_fields=["status", "updated_at"])
    return team


def set_membership_status(membership: TeamMembership, status: str) -> TeamMembership:
    allowed = {
        TeamMembership.Status.ACTIVE,
        TeamMembership.Status.SUSPENDED,
        TeamMembership.Status.REMOVED,
    }
    if status not in allowed:
        raise ValidationError("Invalid membership status.")
    if membership.status != status:
        membership.status = status
        if status == TeamMembership.Status.ACTIVE and not membership.joined_at:
            membership.joined_at = timezone.now()
            membership.save(update_fields=["status", "joined_at", "updated_at"])
        else:
            membership.save(update_fields=["status", "updated_at"])
    return membership
