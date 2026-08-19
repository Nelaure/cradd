from django.urls import path
from . import views

app_name = 'eleves'

urlpatterns = [
    path('', views.eleve_list, name='eleve_list'),
    path('create/', views.eleve_create, name='eleve_create'),
    path('<int:pk>/', views.eleve_detail, name='eleve_detail'),
    path('<int:pk>/edit/', views.eleve_edit, name='eleve_edit'),
    path('<int:pk>/delete/', views.eleve_delete, name='eleve_delete'),
    path('bulletins/create/', views.bulletin_create, name='bulletin_create'),
    path('bulletins/<int:pk>/delete/', views.bulletin_delete, name='bulletin_delete'),
    path('toggle-masquage/', views.toggle_masquage, name='toggle_masquage'),
    path('toggle-colonne-masquage/', views.toggle_colonne_masquage, name='toggle_colonne_masquage'),
]