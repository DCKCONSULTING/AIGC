from django.db import migrations, models


def copy_scene_failures(apps, schema_editor):
    Scene = apps.get_model("ai", "Scene")
    for scene in Scene.objects.all().iterator():
        meta = scene.metadata if isinstance(scene.metadata, dict) else {}
        pipe = meta.get("pipeline_error") if isinstance(meta.get("pipeline_error"), dict) else {}
        status = str(meta.get("status") or "")
        if status != "failed" and not pipe and not meta.get("error"):
            continue
        scene.generation_status = "failed"
        scene.failure_code = str(pipe.get("code") or "")[:64]
        scene.failure_message = str(pipe.get("detail") or meta.get("error") or "")[:500]
        scene.provider = str(pipe.get("provider") or "omni")[:40]
        scene.provider_request_id = str(pipe.get("task_id") or pipe.get("request_id") or "")[:255]
        try:
            scene.retry_count = int(pipe.get("retry_count") or meta.get("retry_count") or 0)
        except (TypeError, ValueError):
            scene.retry_count = 0
        scene.save(
            update_fields=[
                "generation_status",
                "failure_code",
                "failure_message",
                "provider",
                "provider_request_id",
                "retry_count",
            ]
        )


class Migration(migrations.Migration):

    dependencies = [
        ("ai", "0007_characters"),
    ]

    operations = [
        migrations.AddField(
            model_name="scene",
            name="generation_status",
            field=models.CharField(blank=True, max_length=16),
        ),
        migrations.AddField(
            model_name="scene",
            name="failure_code",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="scene",
            name="failure_message",
            field=models.CharField(blank=True, max_length=500),
        ),
        migrations.AddField(
            model_name="scene",
            name="provider",
            field=models.CharField(blank=True, max_length=40),
        ),
        migrations.AddField(
            model_name="scene",
            name="provider_request_id",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="scene",
            name="failed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="scene",
            name="retry_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.RunPython(copy_scene_failures, migrations.RunPython.noop),
    ]
