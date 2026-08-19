from django.urls import path
from . import views

app_name = 'ecoles'

urlpatterns = [
    # Pages publiques
    path('', views.index_view, name='index'),
    path('autocomplete/', views.autocomplete_eleves, name='autocomplete_eleves'),
    path('recherche/', views.recherche_resultats, name='recherche_resultats'),

    # Dashboard
    path('dashboard/', views.dashboard_view, name='dashboard'),

    # RECHERCHE PARENT (NOUVEAU)
    path('parent/recherche/', views.parent_recherche, name='parent_recherche'),

    # Provinces
    path('provinces/', views.province_list, name='province_list'),
    path('provinces/creer/', views.province_create, name='province_create'),
    path('provinces/modifier/<int:pk>/', views.province_edit, name='province_edit'),
    path('provinces/supprimer/<int:pk>/', views.province_delete, name='province_delete'),

    # Écoles
    path('ecoles/', views.ecole_list, name='ecole_list'),
    path('ecoles/creer/', views.ecole_create, name='ecole_create'),
    path('ecoles/modifier/<int:pk>/', views.ecole_edit, name='ecole_edit'),
    path('ecoles/supprimer/<int:pk>/', views.ecole_delete, name='ecole_delete'),

    # Niveaux
    path('niveaux/', views.niveau_list, name='niveau_list'),
    path('niveaux/creer/', views.niveau_create, name='niveau_create'),
    path('niveaux/modifier/<int:pk>/', views.niveau_edit, name='niveau_edit'),
    path('niveaux/supprimer/<int:pk>/', views.niveau_delete, name='niveau_delete'),
    path('niveaux/affecter/<int:pk>/', views.niveau_affecter_ecole, name='niveau_affecter'),

    # Classes
    path('classes/', views.classe_list, name='classe_list'),
    path('classes/creer/', views.classe_create, name='classe_create'),
    path('classes/modifier/<int:pk>/', views.classe_edit, name='classe_edit'),
    path('classes/supprimer/<int:pk>/', views.classe_delete, name='classe_delete'),

    # Domaines
    path('domaines/', views.domaine_list, name='domaine_list'),
    path('domaines/creer/', views.domaine_create, name='domaine_create'),
    path('domaines/modifier/<int:pk>/', views.domaine_edit, name='domaine_edit'),
    path('domaines/supprimer/<int:pk>/', views.domaine_delete, name='domaine_delete'),

    # Cours
    path('cours/', views.cours_list, name='cours_list'),
    path('cours/creer/', views.cours_create, name='cours_create'),
    path('cours/modifier/<int:pk>/', views.cours_edit, name='cours_edit'),
    path('cours/supprimer/<int:pk>/', views.cours_delete, name='cours_delete'),

    # Années scolaires
    path('annees/', views.annee_list, name='annee_list'),
    path('annees/creer/', views.annee_create, name='annee_create'),
    path('annees/modifier/<int:pk>/', views.annee_edit, name='annee_edit'),
    path('annees/supprimer/<int:pk>/', views.annee_delete, name='annee_delete'),

    # Résultats
    path('resultats/', views.resultat_list, name='resultat_list'),
    path('resultats/creer/', views.resultat_create, name='resultat_create'),
    path('resultats/modifier/<int:pk>/', views.resultat_edit, name='resultat_edit'),
    path('resultats/supprimer/<int:pk>/', views.resultat_delete, name='resultat_delete'),

    # Bulletins
    path('bulletins/', views.bulletin_view, name='bulletin_view'),
    path('eleves-sans-notes/', views.eleves_sans_notes, name='eleves_sans_notes'),

    # Corbeille
    path('corbeille/', views.trash_list, name='trash_list'),
    path('corbeille/restaurer/<str:model_name>/<int:pk>/', views.restore_item, name='restore_item'),
    path('corbeille/supprimer/<str:model_name>/<int:pk>/', views.permanent_delete, name='permanent_delete'),
    path('corbeille/vider/', views.empty_trash, name='empty_trash'),

    # API
    path('api/niveaux/', views.api_get_niveaux, name='api_get_niveaux'),
    path('api/classes/', views.api_get_classes, name='api_get_classes'),
    path('api/classes-par-niveau/', views.api_get_classes_by_niveau, name='api_get_classes_by_niveau'),
    path('api/domaines-par-niveau/', views.api_get_domaines_by_niveau, name='api_get_domaines_by_niveau'),
    path('api/eleves/', views.api_get_eleves, name='api_get_eleves'),
    path('api/cours/', views.api_get_cours, name='api_get_cours'),
]