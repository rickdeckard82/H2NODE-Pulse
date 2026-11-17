import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class WikiPage(models.Model):
    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    title = models.CharField(max_length=200)
    body = models.TextField()
    # Short labels shown as colored chips and used as the side menu filter.
    tags = models.JSONField(default=list)
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="wiki_pages"
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="+"
    )
    # Empty = visible to every signed-in user. Otherwise only members of these groups
    # (and managers/administrators) see it. PROTECT: a purged group must never make
    # a restricted page public.
    groups = models.ManyToManyField(
        "core.SupportGroup", through="WikiPageGroup", related_name="wiki_pages", blank=True
    )
    # Same rule for areas (departments), which is how collaborators belong to the audience:
    # they cannot be members of support groups.
    departments = models.ManyToManyField(
        "core.Department", through="WikiPageDepartment", related_name="wiki_pages", blank=True
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ["-created_at", "-id"]


class WikiPageGroup(models.Model):
    page = models.ForeignKey(WikiPage, on_delete=models.CASCADE)
    group = models.ForeignKey("core.SupportGroup", on_delete=models.PROTECT)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["page", "group"], name="wiki_page_group")]


class WikiPageDepartment(models.Model):
    page = models.ForeignKey(WikiPage, on_delete=models.CASCADE)
    department = models.ForeignKey("core.Department", on_delete=models.PROTECT)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["page", "department"], name="wiki_page_department")
        ]


class WikiFile(models.Model):
    """Image or attachment used by wiki pages. Stored privately; only clean files exist."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120)
    media_type = models.CharField(max_length=120)
    size = models.PositiveIntegerField()
    sha256 = models.CharField(max_length=64)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)
