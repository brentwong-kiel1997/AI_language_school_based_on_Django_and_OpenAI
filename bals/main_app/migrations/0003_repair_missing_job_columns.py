from django.db import migrations


REPAIR_FIELDS = ("status", "error_message", "created_at", "updated_at")
REPAIR_MODELS = ("Transcribed_Video", "Learning_Material")


def add_missing_job_columns(apps, schema_editor):
    connection = schema_editor.connection

    for model_name in REPAIR_MODELS:
        model = apps.get_model("main_app", model_name)
        table_name = model._meta.db_table

        with connection.cursor() as cursor:
            table_names = connection.introspection.table_names(cursor)
        if table_name not in table_names:
            continue

        for field_name in REPAIR_FIELDS:
            # SQLite may rebuild the table while adding a non-null field, so
            # introspect again before each addition instead of caching names.
            with connection.cursor() as cursor:
                columns = {
                    column.name
                    for column in connection.introspection.get_table_description(
                        cursor, table_name
                    )
                }
            if field_name not in columns:
                schema_editor.add_field(model, model._meta.get_field(field_name))


class Migration(migrations.Migration):
    dependencies = [
        ("main_app", "0002_transcribed_video_created_at_and_more"),
    ]

    operations = [
        migrations.RunPython(add_missing_job_columns, migrations.RunPython.noop),
    ]
