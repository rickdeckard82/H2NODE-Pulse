from django.contrib.auth.models import AbstractUser


class User(AbstractUser):
    """Identity anchor; corporate registration and roles arrive in stage 2."""
