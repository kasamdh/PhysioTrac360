from django.db import migrations


def backfill_status(apps, schema_editor):
    User = apps.get_model("care", "User")
    User.objects.filter(archived_at__isnull=False).update(status="deleted")
    User.objects.filter(archived_at__isnull=True, is_active=False).update(status="inactive")
    User.objects.filter(archived_at__isnull=True, is_active=True).update(status="active")


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('care', '0017_user_failed_login_attempts_user_last_failed_login_at_and_more'),
    ]

    operations = [
        migrations.RunPython(backfill_status, noop),
    ]
