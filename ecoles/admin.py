from django.contrib import admin
from .models import (
    Ecole, Niveau, Classe, Domaine, Cours,
    AnneeScolaire, CycleEvaluation, EvaluationConfig,
    EvaluationResultat, ResultatCycle, ResultatAnnuel
)

@admin.register(Ecole)
class EcoleAdmin(admin.ModelAdmin):
    list_display = ['nom', 'code', 'province', 'est_active']
    search_fields = ['nom', 'code']

@admin.register(Niveau)
class NiveauAdmin(admin.ModelAdmin):
    list_display = ['nom', 'ecole', 'est_reference', 'ordre']
    list_filter = ['ecole', 'est_reference']

@admin.register(Classe)
class ClasseAdmin(admin.ModelAdmin):
    list_display = ['nom', 'niveau', 'ecole', 'est_reference']
    list_filter = ['ecole', 'est_reference', 'niveau']

@admin.register(Domaine)
class DomaineAdmin(admin.ModelAdmin):
    list_display = ['nom', 'ecole', 'est_reference']
    list_filter = ['ecole', 'est_reference']

@admin.register(Cours)
class CoursAdmin(admin.ModelAdmin):
    list_display = ['nom', 'code', 'coefficient', 'classe', 'domaine', 'ecole', 'est_reference']
    list_filter = ['ecole', 'est_reference', 'classe', 'domaine']
    search_fields = ['nom', 'code']

@admin.register(AnneeScolaire)
class AnneeScolaireAdmin(admin.ModelAdmin):
    list_display = ['annee', 'date_debut', 'date_fin', 'est_actuelle']

@admin.register(CycleEvaluation)
class CycleEvaluationAdmin(admin.ModelAdmin):
    list_display = ['cours', 'type_cycle']

@admin.register(EvaluationConfig)
class EvaluationConfigAdmin(admin.ModelAdmin):
    list_display = ['cycle_evaluation', 'cycle_num', 'type', 'points_max']

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