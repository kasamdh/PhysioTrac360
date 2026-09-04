"""Create or refresh the platform super administrator for a local demo."""
from django.core.management.base import BaseCommand, CommandError

from care.models import User


class Command(BaseCommand):
    help = "Create or refresh the local platform super administrator."

    def add_arguments(self, parser):
        parser.add_argument("--username", default="clinic_admin")
        parser.add_argument("--password", required=True)

    def handle(self, *args, **options):
        username = options["username"].strip()
        if not username:
            raise CommandError("Username is required.")
        user, created = User.objects.get_or_create(username=username)
        user.organization = None
        user.role = User.Role.SUPER_ADMIN
        user.is_superuser = True
        user.is_staff = True
        user.is_active = True
        user.must_use_mfa = True
        user.set_password(options["password"])
        user.full_clean()
        user.save()
        action = "Created" if created else "Refreshed"
        self.stdout.write(
            self.style.SUCCESS(
                "%s platform super administrator %s. This command is for local "
                "development only; use a unique password and enterprise identity "
                "provider before production." % (action, user.username)
            )
        )
