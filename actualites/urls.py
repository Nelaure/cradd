from django.urls import path
from . import views

app_name = 'actualites'

urlpatterns = [
    # Dashboard & articles
    path('dashboard/', views.dashboard, name='dashboard'),
    path('creer/', views.article_create, name='article_create'),
    path('<int:pk>/modifier/', views.article_edit, name='article_edit'),
    path('<int:pk>/supprimer/', views.article_delete, name='article_delete'),

    # Corbeille
    path('trash/', views.trash_list, name='trash_list'),
    path('trash/<int:pk>/restaurer/', views.restore_article, name='restore_article'),
    path('trash/<int:pk>/supprimer-definitivement/', views.hard_delete_article, name='hard_delete_article'),
    path('trash/vider/', views.empty_trash, name='empty_trash'),

    # Catégories
    path('categories/', views.categorie_list, name='categorie_list'),
    path('categories/creer/', views.categorie_create, name='categorie_create'),
    path('categories/<int:pk>/modifier/', views.categorie_edit, name='categorie_edit'),
    path('categories/<int:pk>/supprimer/', views.categorie_delete, name='categorie_delete'),

    # Vues publiques (en dernier)
    path('', views.article_list, name='article_list'),
    path('<slug:slug>/', views.article_detail, name='article_detail'),
]