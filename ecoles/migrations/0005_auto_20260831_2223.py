from django.db import migrations

def clean_duplicate_configs(apps, schema_editor):
    EvaluationConfig = apps.get_model('ecoles', 'EvaluationConfig')
    seen = set()
    to_delete = []
    for config in EvaluationConfig.objects.order_by('cycle_evaluation_id', 'cycle_num', 'ordre'):
        key = (config.cycle_evaluation_id, config.cycle_num, config.periode_num, config.type)
        if key in seen:
            to_delete.append(config.id)
        else:
            seen.add(key)
    if to_delete:
        EvaluationConfig.objects.filter(id__in=to_delete).delete()

class Migration(migrations.Migration):
    dependencies = [
        ('ecoles', '0004_remove_cours_reference'),  # <- CORRECTION ICI
    ]
    operations = [
        migrations.RunPython(clean_duplicate_configs),
    ]