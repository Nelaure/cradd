# ============================================================================
# ecoles/admin.py
# ============================================================================

from django.contrib import admin
from .models import (
    Ecole, Niveau, Classe, Cours,
    AnneeScolaire, CycleEvaluation, EvaluationConfig,
    EvaluationResultat, ResultatCycle, ResultatAnnuel,
    Province, Section
)


@admin.register(Province)
class ProvinceAdmin(admin.ModelAdmin):
    list_display = ['nom', 'code']
    search_fields = ['nom', 'code']


@admin.register(Section)
class SectionAdmin(admin.ModelAdmin):
    list_display = ['nom', 'code', 'ordre']
    ordering = ['ordre', 'nom']
    search_fields = ['nom', 'code']


@admin.register(Ecole)
class EcoleAdmin(admin.ModelAdmin):
    list_display = ['nom', 'code', 'province', 'est_active']
    search_fields = ['nom', 'code']
    list_filter = ['province', 'est_active']


@admin.register(Niveau)
class NiveauAdmin(admin.ModelAdmin):
    list_display = ['nom', 'ecole', 'est_reference', 'ordre', 'section']
    list_filter = ['ecole', 'est_reference', 'section']
    search_fields = ['nom']


@admin.register(Classe)
class ClasseAdmin(admin.ModelAdmin):
    list_display = ['nom', 'niveau', 'ecole', 'est_reference']
    list_filter = ['ecole', 'est_reference', 'niveau']
    search_fields = ['nom']


@admin.register(Cours)
class CoursAdmin(admin.ModelAdmin):
    list_display = ['nom', 'code', 'coefficient', 'classe', 'ecole', 'est_reference']
    list_filter = ['ecole', 'est_reference', 'classe']
    search_fields = ['nom', 'code']


@admin.register(AnneeScolaire)
class AnneeScolaireAdmin(admin.ModelAdmin):
    list_display = ['annee', 'date_debut', 'date_fin', 'est_actuelle']
    list_filter = ['est_actuelle']


@admin.register(CycleEvaluation)
class CycleEvaluationAdmin(admin.ModelAdmin):
    list_display = ['cours', 'type_cycle']
    list_filter = ['type_cycle']


@admin.register(EvaluationConfig)
class EvaluationConfigAdmin(admin.ModelAdmin):
    list_display = ['cycle_evaluation', 'cycle_num', 'type', 'points_max']
    list_filter = ['type']


@admin.register(EvaluationResultat)
class EvaluationResultatAdmin(admin.ModelAdmin):
    list_display = ['eleve', 'cours', 'evaluation_config', 'points_obtenus']
    list_filter = ['cours', 'annee_scolaire']


@admin.register(ResultatCycle)
class ResultatCycleAdmin(admin.ModelAdmin):
    list_display = ['eleve', 'cours', 'cycle_num', 'pourcentage']


@admin.register(ResultatAnnuel)
class ResultatAnnuelAdmin(admin.ModelAdmin):
    list_display = ['eleve', 'annee_scolaire', 'moyenne_generale', 'pourcentage_general']