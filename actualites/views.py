from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.core.paginator import Paginator
from django.utils import timezone
from django.db.models import Count, Q
from .models import Article, Categorie
from .forms import ArticleForm, CategorieForm
from accounts.views import log_audit, get_client_ip
from accounts.models import AuditLog

# Import de la fonction de géolocalisation depuis ecoles.views
# Si elle n'existe pas, vous pouvez la définir ici ou dans un module utils
from ecoles.views import get_geo_data_from_ips

# ==================== VÉRIFICATION DES PERMISSIONS ====================

def est_editeur_ou_admin(user):
    """Vérifie si l'utilisateur est éditeur ou administrateur"""
    return user.is_authenticated and (user.est_editeur() or user.est_administrateur())


# ==================== DASHBOARD ====================

@login_required
@user_passes_test(est_editeur_ou_admin)
def dashboard(request):
    """
    Tableau de bord de l'éditeur.
    - Liste des articles actifs (non supprimés)
    - Statistiques : total, publiés, brouillons, vues totales
    - Pour chaque article : nombre de vues et top 5 pays des visiteurs
    """
    user = request.user

    # Récupération des articles actifs (non supprimés)
    if user.est_administrateur():
        articles_qs = Article.active_objects().order_by('-date_creation')
    else:
        articles_qs = Article.active_objects().filter(auteur=user).order_by('-date_creation')

    # Statistiques globales
    articles_count = articles_qs.count()
    published_count = articles_qs.filter(statut=Article.Statut.PUBLIE).count()
    draft_count = articles_qs.filter(statut=Article.Statut.BROUILLON).count()

    # Récupération des IDs des articles actifs
    article_ids = list(articles_qs.values_list('id', flat=True))

    # Récupération des logs de type VIEW pour ces articles
    view_logs = AuditLog.objects.filter(
        action=AuditLog.ActionType.VIEW,
        model_name='Article',
        object_id__in=[str(id) for id in article_ids],
        success=True
    ).values('object_id', 'ip_address', 'timestamp')

    total_views = view_logs.count()

    # Compter les vues par article et récupérer les IPs par article
    views_per_article = {}
    ips_per_article = {}
    for log in view_logs:
        obj_id = int(log['object_id'])
        views_per_article[obj_id] = views_per_article.get(obj_id, 0) + 1
        if log['ip_address']:
            ips_per_article.setdefault(obj_id, []).append(log['ip_address'])

    # Géolocalisation : pour chaque article, on récupère les pays les plus fréquents
    top_countries_per_article = {}
    for article_id, ips in ips_per_article.items():
        if ips:
            geo_result = get_geo_data_from_ips(ips)
            # geo_result['country_items'] = liste de tuples (pays, count)
            top_countries = [country for country, _ in geo_result['country_items'][:5]]
            top_countries_per_article[article_id] = top_countries
        else:
            top_countries_per_article[article_id] = []

    # Pagination
    paginator = Paginator(articles_qs, 10)
    page = request.GET.get('page')
    articles_page = paginator.get_page(page)

    # Ajouter les attributs views_count et top_countries à chaque article
    for article in articles_page:
        article.views_count = views_per_article.get(article.id, 0)
        article.top_countries = top_countries_per_article.get(article.id, [])

    context = {
        'articles': articles_page,
        'articles_count': articles_count,
        'published_count': published_count,
        'draft_count': draft_count,
        'total_views': total_views,
    }
    return render(request, 'actualites/dashboard.html', context)


# ==================== CRUD ARTICLES (avec soft delete) ====================

@login_required
@user_passes_test(est_editeur_ou_admin)
def article_create(request):
    """Créer un nouvel article"""
    if request.method == 'POST':
        form = ArticleForm(request.POST, request.FILES)
        if form.is_valid():
            article = form.save(commit=False)
            article.auteur = request.user
            article.save()

            # Journalisation
            ip = get_client_ip(request)
            user_agent = request.META.get('HTTP_USER_AGENT', '')
            log_audit(
                user=request.user,
                action=AuditLog.ActionType.CREATE,
                model_name='Article',
                object_id=article.id,
                object_repr=article.titre,
                ip_address=ip,
                user_agent=user_agent,
                success=True,
                message=f"Création de l'article '{article.titre}'"
            )

            messages.success(request, f"Article '{article.titre}' créé avec succès.")
            return redirect('actualites:dashboard')
        else:
            messages.error(request, 'Veuillez corriger les erreurs ci-dessous.')
    else:
        form = ArticleForm()

    return render(request, 'actualites/article_form.html', {
        'form': form,
        'title': 'Créer un article'
    })


@login_required
@user_passes_test(est_editeur_ou_admin)
def article_edit(request, pk):
    """Modifier un article existant (non supprimé)"""
    article = get_object_or_404(Article.active_objects(), pk=pk)

    if not request.user.est_administrateur() and article.auteur != request.user:
        messages.error(request, "Vous n'êtes pas autorisé à modifier cet article.")
        return redirect('actualites:dashboard')

    if request.method == 'POST':
        form = ArticleForm(request.POST, request.FILES, instance=article)
        if form.is_valid():
            form.save()

            ip = get_client_ip(request)
            user_agent = request.META.get('HTTP_USER_AGENT', '')
            log_audit(
                user=request.user,
                action=AuditLog.ActionType.UPDATE,
                model_name='Article',
                object_id=article.id,
                object_repr=article.titre,
                ip_address=ip,
                user_agent=user_agent,
                success=True,
                message=f"Modification de l'article '{article.titre}'"
            )

            messages.success(request, f"Article '{article.titre}' modifié avec succès.")
            return redirect('actualites:dashboard')
        else:
            messages.error(request, 'Veuillez corriger les erreurs ci-dessous.')
    else:
        form = ArticleForm(instance=article)

    return render(request, 'actualites/article_form.html', {
        'form': form,
        'title': 'Modifier un article'
    })


@login_required
@user_passes_test(est_editeur_ou_admin)
def article_delete(request, pk):
    """Déplace l'article vers la corbeille (soft delete)"""
    article = get_object_or_404(Article.active_objects(), pk=pk)

    if not request.user.est_administrateur() and article.auteur != request.user:
        messages.error(request, "Vous n'êtes pas autorisé à supprimer cet article.")
        return redirect('actualites:dashboard')

    if request.method == 'POST':
        titre = article.titre
        article.delete()  # soft delete : marque deleted_at

        ip = get_client_ip(request)
        user_agent = request.META.get('HTTP_USER_AGENT', '')
        log_audit(
            user=request.user,
            action=AuditLog.ActionType.DELETE,
            model_name='Article',
            object_id=article.id,
            object_repr=titre,
            ip_address=ip,
            user_agent=user_agent,
            success=True,
            message=f"Suppression (soft delete) de l'article '{titre}'"
        )

        messages.success(request, f"L'article '{titre}' a été déplacé dans la corbeille.")
        return redirect('actualites:dashboard')

    return render(request, 'actualites/article_confirm_delete.html', {'article': article})


# ==================== CORBEILLE ====================

@login_required
@user_passes_test(est_editeur_ou_admin)
def trash_list(request):
    """Liste des articles dans la corbeille (supprimés)"""
    if request.user.est_administrateur():
        articles = Article.all_objects().filter(deleted_at__isnull=False).order_by('-deleted_at')
    else:
        articles = Article.all_objects().filter(deleted_at__isnull=False, auteur=request.user).order_by('-deleted_at')

    paginator = Paginator(articles, 10)
    page = request.GET.get('page')
    articles = paginator.get_page(page)

    return render(request, 'actualites/article_trash_list.html', {'articles': articles})


@login_required
@user_passes_test(est_editeur_ou_admin)
def restore_article(request, pk):
    """Restaure un article depuis la corbeille"""
    article = get_object_or_404(Article.all_objects(), pk=pk, deleted_at__isnull=False)

    if not request.user.est_administrateur() and article.auteur != request.user:
        messages.error(request, "Vous n'êtes pas autorisé à restaurer cet article.")
        return redirect('actualites:trash_list')

    article.restore()
    messages.success(request, f"L'article '{article.titre}' a été restauré avec succès.")
    return redirect('actualites:trash_list')


@login_required
@user_passes_test(est_editeur_ou_admin)
def hard_delete_article(request, pk):
    """Supprime définitivement un article de la base de données"""
    article = get_object_or_404(Article.all_objects(), pk=pk, deleted_at__isnull=False)

    if not request.user.est_administrateur() and article.auteur != request.user:
        messages.error(request, "Vous n'êtes pas autorisé à supprimer définitivement cet article.")
        return redirect('actualites:trash_list')

    if request.method == 'POST':
        titre = article.titre
        article.hard_delete()
        messages.success(request, f"L'article '{titre}' a été supprimé définitivement.")
        return redirect('actualites:trash_list')

    return render(request, 'actualites/article_confirm_hard_delete.html', {'article': article})


@login_required
@user_passes_test(est_editeur_ou_admin)
def empty_trash(request):
    """Vide la corbeille (supprime définitivement tous les articles supprimés)"""
    if request.user.est_administrateur():
        articles = Article.all_objects().filter(deleted_at__isnull=False)
    else:
        articles = Article.all_objects().filter(deleted_at__isnull=False, auteur=request.user)

    if request.method == 'POST':
        count = articles.count()
        for article in articles:
            article.hard_delete()
        messages.success(request, f"La corbeille a été vidée ({count} article(s) supprimé(s) définitivement).")
        return redirect('actualites:trash_list')

    return render(request, 'actualites/trash_confirm_empty.html', {'articles': articles})


# ==================== VUES PUBLIQUES ====================

def article_list(request):
    """Liste publique des articles publiés et visibles"""
    articles = Article.objects.filter(
        statut=Article.Statut.PUBLIE,
        est_visible=True,
        deleted_at__isnull=True   # exclure les supprimés
    ).order_by('-date_publication')

    paginator = Paginator(articles, 10)
    page = request.GET.get('page')
    articles = paginator.get_page(page)

    return render(request, 'actualites/article_list_public.html', {'articles': articles})


def article_detail(request, slug):
    """
    Détail d'un article.
    - Si l'utilisateur est connecté et est éditeur/admin, il peut voir même les brouillons/masqués.
    - Sinon, il ne voit que les articles publiés et visibles, non supprimés.
    - Enregistre une vue (via AuditLog) pour les visiteurs publics.
    """
    if request.user.is_authenticated and (request.user.est_editeur() or request.user.est_administrateur()):
        # L'éditeur/admin voit tous les articles (même supprimés ? normalement non, on exclut les supprimés)
        # On lui permet de voir les brouillons, masqués, mais pas les supprimés.
        article = get_object_or_404(Article.active_objects(), slug=slug)
    else:
        # Public : uniquement publiés, visibles, non supprimés
        article = get_object_or_404(
            Article.active_objects(),
            slug=slug,
            statut=Article.Statut.PUBLIE,
            est_visible=True
        )
        # Enregistrer la vue uniquement pour les visiteurs publics
        ip = get_client_ip(request)
        user_agent = request.META.get('HTTP_USER_AGENT', '')
        log_audit(
            user=None,  # utilisateur anonyme
            action=AuditLog.ActionType.VIEW,
            model_name='Article',
            object_id=article.id,
            object_repr=article.titre,
            ip_address=ip,
            user_agent=user_agent,
            success=True,
            message=f"Consultation publique de l'article '{article.titre}'"
        )

    return render(request, 'actualites/article_detail_public.html', {'article': article})


# ==================== CATÉGORIES (CRUD) ====================

@login_required
@user_passes_test(est_editeur_ou_admin)
def categorie_list(request):
    categories = Categorie.objects.all().order_by('nom')
    return render(request, 'actualites/categorie_list.html', {'categories': categories})


@login_required
@user_passes_test(est_editeur_ou_admin)
def categorie_create(request):
    if request.method == 'POST':
        form = CategorieForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Catégorie créée avec succès.")
            return redirect('actualites:categorie_list')
        else:
            messages.error(request, 'Veuillez corriger les erreurs ci-dessous.')
    else:
        form = CategorieForm()

    return render(request, 'actualites/categorie_form.html', {
        'form': form,
        'title': 'Créer une catégorie'
    })


@login_required
@user_passes_test(est_editeur_ou_admin)
def categorie_edit(request, pk):
    categorie = get_object_or_404(Categorie, pk=pk)

    if request.method == 'POST':
        form = CategorieForm(request.POST, instance=categorie)
        if form.is_valid():
            form.save()
            messages.success(request, "Catégorie mise à jour avec succès.")
            return redirect('actualites:categorie_list')
        else:
            messages.error(request, 'Veuillez corriger les erreurs ci-dessous.')
    else:
        form = CategorieForm(instance=categorie)

    return render(request, 'actualites/categorie_form.html', {
        'form': form,
        'title': 'Modifier la catégorie'
    })


@login_required
@user_passes_test(est_editeur_ou_admin)
def categorie_delete(request, pk):
    categorie = get_object_or_404(Categorie, pk=pk)

    if request.method == 'POST':
        nom = categorie.nom
        categorie.delete()
        messages.success(request, f"Catégorie '{nom}' supprimée avec succès.")
        return redirect('actualites:categorie_list')

    return render(request, 'actualites/categorie_confirm_delete.html', {'categorie': categorie})