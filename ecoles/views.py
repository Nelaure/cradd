import requests
from collections import Counter
from datetime import datetime, timedelta
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q, Sum, Count, Avg, F
from django.urls import reverse
from django.http import JsonResponse
from .models import (
    Ecole, Niveau, Classe, Domaine, Cours, AnneeScolaire,
    CycleEvaluation, EvaluationConfig, EvaluationResultat,
    ResultatCycle, ResultatAnnuel, Province
)
from .forms import (
    EcoleForm, NiveauForm, ClasseForm, DomaineForm, CoursForm,
    AnneeScolaireForm, CycleEvaluationForm, EvaluationConfigFormSet,
    ResultatSelectionForm, EvaluationResultatForm, ProvinceForm
)
from eleves.models import Eleve
from .utils import recalculer_resultats_eleve
from accounts.models import AuditLog

# ===================== FONCTIONS UTILITAIRES =====================

def get_annee_actuelle():
    """Retourne l'année scolaire actuelle ou la dernière créée."""
    annee = AnneeScolaire.objects.filter(est_actuelle=True).first()
    if not annee:
        annee = AnneeScolaire.objects.order_by('-annee').first()
    return annee

def calculer_taux_reussite(queryset_resultats, seuil=10):
    """Calcule le taux de réussite pour un queryset de ResultatAnnuel."""
    total = queryset_resultats.count()
    if total == 0:
        return 0
    reussis = queryset_resultats.filter(moyenne_generale__gte=seuil).count()
    return round((reussis / total) * 100, 1)

def calculer_moyenne_generale(queryset_resultats):
    """Calcule la moyenne générale des moyennes d'un queryset de ResultatAnnuel."""
    avg = queryset_resultats.aggregate(avg=Avg('moyenne_generale'))['avg']
    return round(avg, 2) if avg is not None else 0

# ===================== FONCTIONS DE GÉOLOCALISATION =====================

def get_geo_data_from_ips(ips):
    """
    Prend une liste d'adresses IP et retourne les comptages par pays et par ville.
    Retourne un dictionnaire avec les items et les totaux.
    """
    country_counts = {}
    city_counts = {}
    city_detail = {}
    for ip in ips:
        if not ip:
            continue
        try:
            response = requests.get(
                f'http://ip-api.com/json/{ip}?fields=country,city',
                timeout=3
            )
            if response.status_code == 200:
                data = response.json()
                country = data.get('country', 'Inconnu')
                city = data.get('city', 'Inconnu')
                country_counts[country] = country_counts.get(country, 0) + 1
                key = f"{country} - {city}"
                city_counts[key] = city_counts.get(key, 0) + 1
                city_detail[key] = {'country': country, 'city': city}
        except:
            pass

    sorted_countries = sorted(country_counts.items(), key=lambda x: x[1], reverse=True)
    sorted_cities = sorted(city_counts.items(), key=lambda x: x[1], reverse=True)

    country_items = sorted_countries[:10]
    city_items = []
    for key, count in sorted_cities[:10]:
        city_items.append({
            'country': city_detail[key]['country'],
            'city': city_detail[key]['city'],
            'count': count
        })

    return {
        'country_items': country_items,
        'city_items': city_items,
        'total_pays': len(country_counts),
        'total_villes': len(city_counts),
        'country_labels': [c[0] for c in country_items],
        'country_data': [c[1] for c in country_items],
    }

def get_cached_geo_data(request, cache_key, ips_function, ttl_minutes=10):
    """
    Récupère les données de géolocalisation avec cache en session.
    `ips_function` doit être une fonction qui retourne une liste d'IPs.
    """
    now = datetime.now()
    cache_data = None
    cache_time_key = f"{cache_key}_time"

    if cache_key in request.session and cache_time_key in request.session:
        try:
            cache_time_str = request.session[cache_time_key]
            cache_time = datetime.fromisoformat(cache_time_str)
            if now - cache_time < timedelta(minutes=ttl_minutes):
                cache_data = request.session[cache_key]
        except (ValueError, TypeError):
            pass

    if cache_data is None:
        ips = list(ips_function())
        if ips:
            geo_result = get_geo_data_from_ips(ips)
            cache_data = {
                'country_items': geo_result['country_items'],
                'city_items': geo_result['city_items'],
                'total_pays': geo_result['total_pays'],
                'total_villes': geo_result['total_villes'],
                'country_labels': geo_result['country_labels'],
                'country_data': geo_result['country_data'],
            }
        else:
            cache_data = {
                'country_items': [],
                'city_items': [],
                'total_pays': 0,
                'total_villes': 0,
                'country_labels': [],
                'country_data': [],
            }
        request.session[cache_key] = cache_data
        request.session[cache_time_key] = now.isoformat()

    return cache_data

# ===================== PAGE D'ACCUEIL PUBLIQUE =====================
def index_view(request):
    return render(request, 'ecoles/index.html')

# ===================== TABLEAU DE BORD PAR RÔLE =====================
@login_required
def dashboard_view(request):
    user = request.user
    annee_actuelle = get_annee_actuelle()
    context = {
        'annee_actuelle': annee_actuelle,
        'user_role': user.role,
        'user_full_name': user.get_full_name(),
        'user_ecole': user.ecole_affectation,
        'user_province': user.province_affectation,
        'user_classe': user.classe_affectation,
        'total_annees': AnneeScolaire.objects.count(),
    }

    # --- ADMIN ---
    if user.est_administrateur():
        province_id = request.GET.get('province')
        province_filter = None
        if province_id:
            try:
                province_filter = Province.objects.get(pk=province_id)
            except Province.DoesNotExist:
                province_filter = None

        # Base des querysets
        ecoles_qs = Ecole.objects.all()
        eleves_qs = Eleve.objects.all()
        niveaux_qs = Niveau.objects.filter(est_reference=False)
        classes_qs = Classe.objects.filter(est_reference=False)
        cours_qs = Cours.objects.filter(est_reference=False)
        resultats_qs = EvaluationResultat.objects.all()
        resultats_annuels_qs = ResultatAnnuel.objects.all()

        if province_filter:
            ecoles_qs = ecoles_qs.filter(province=province_filter)
            eleves_qs = eleves_qs.filter(ecole__province=province_filter)
            niveaux_qs = niveaux_qs.filter(ecole__province=province_filter)
            classes_qs = classes_qs.filter(ecole__province=province_filter)
            cours_qs = cours_qs.filter(ecole__province=province_filter)
            resultats_qs = resultats_qs.filter(eleve__ecole__province=province_filter)
            resultats_annuels_qs = resultats_annuels_qs.filter(eleve__ecole__province=province_filter)

        # Statistiques globales
        total_ecoles = ecoles_qs.count()
        total_niveaux = niveaux_qs.count()
        total_classes = classes_qs.count()
        total_cours = cours_qs.count()
        total_eleves = eleves_qs.count()
        total_notes = resultats_qs.filter(annee_scolaire=annee_actuelle).count() if annee_actuelle else 0

        # Résultats annuels
        if annee_actuelle:
            resultats_annuels_qs = resultats_annuels_qs.filter(annee_scolaire=annee_actuelle)
        moyenne_generale_globale = calculer_moyenne_generale(resultats_annuels_qs)
        taux_reussite_global = calculer_taux_reussite(resultats_annuels_qs)

        # Graphiques : élèves par école
        eleves_par_ecole = (
            eleves_qs.values('ecole__nom')
            .annotate(total=Count('id'))
            .order_by('ecole__nom')
        )
        ecole_labels = [item['ecole__nom'] for item in eleves_par_ecole]
        ecole_counts = [item['total'] for item in eleves_par_ecole]

        # Répartition par sexe
        eleves_par_sexe = (
            eleves_qs.values('sexe')
            .annotate(total=Count('id'))
        )
        sexe_map = dict(Eleve.SEXE_CHOICES)
        sexe_labels = [sexe_map.get(item['sexe'], item['sexe']) for item in eleves_par_sexe]
        sexe_counts = [item['total'] for item in eleves_par_sexe]

        # Élèves par niveau
        eleves_par_niveau = (
            eleves_qs.values('niveau__nom')
            .annotate(total=Count('id'))
            .order_by('niveau__nom')
        )
        niveau_labels = [item['niveau__nom'] or 'Non défini' for item in eleves_par_niveau]
        niveau_counts = [item['total'] for item in eleves_par_niveau]

        # Statistiques par école
        stats_par_ecole = []
        for ecole in ecoles_qs:
            res = resultats_annuels_qs.filter(eleve__ecole=ecole)
            if res.exists():
                total = res.count()
                reussis = res.filter(moyenne_generale__gte=10).count()
                taux = (reussis / total * 100) if total > 0 else 0
                stats_par_ecole.append({
                    'nom': ecole.nom,
                    'total': total,
                    'reussis': reussis,
                    'taux': round(taux, 1)
                })
            else:
                nb_eleves = eleves_qs.filter(ecole=ecole).count()
                stats_par_ecole.append({
                    'nom': ecole.nom,
                    'total': nb_eleves,
                    'reussis': 0,
                    'taux': 0
                })
        stats_par_ecole = sorted(stats_par_ecole, key=lambda x: x['taux'], reverse=True)

        provinces = Province.objects.all().order_by('nom')

        # ============================================================
        # STATISTIQUES DE GÉOLOCALISATION (VISITEURS + UTILISATEURS)
        # ============================================================

        # 1. Visiteurs anonymes (actions VIEW sur les 7 derniers jours)
        seven_days_ago = datetime.now() - timedelta(days=7)
        view_ips = AuditLog.objects.filter(
            action=AuditLog.ActionType.VIEW,
            success=True,
            timestamp__gte=seven_days_ago
        ).values_list('ip_address', flat=True).distinct()[:100]

        visitor_data = get_cached_geo_data(
            request,
            'visitor_geo_cache',
            lambda: view_ips,
            ttl_minutes=10
        )

        # 2. Utilisateurs connectés (actions LOGIN)
        login_ips = AuditLog.objects.filter(
            action=AuditLog.ActionType.LOGIN,
            success=True
        ).values_list('ip_address', flat=True).distinct()[:100]

        user_data = get_cached_geo_data(
            request,
            'user_geo_cache',
            lambda: login_ips,
            ttl_minutes=10
        )

        context.update({
            'role': 'admin',
            'total_ecoles': total_ecoles,
            'total_niveaux': total_niveaux,
            'total_classes': total_classes,
            'total_cours': total_cours,
            'total_eleves': total_eleves,
            'total_notes': total_notes,
            'moyenne_generale_globale': moyenne_generale_globale,
            'taux_reussite_global': taux_reussite_global,
            'ecole_labels': ecole_labels,
            'ecole_counts': ecole_counts,
            'sexe_labels': sexe_labels,
            'sexe_counts': sexe_counts,
            'niveau_labels': niveau_labels,
            'niveau_counts': niveau_counts,
            'stats_par_ecole': stats_par_ecole,
            'provinces': provinces,
            'province_filter': province_filter,
            # Données visiteurs
            'visitor_country_items': visitor_data['country_items'],
            'visitor_city_items': visitor_data['city_items'],
            'visitor_country_labels': visitor_data['country_labels'],
            'visitor_country_data': visitor_data['country_data'],
            'total_visitor_pays': visitor_data['total_pays'],
            'total_visitor_villes': visitor_data['total_villes'],
            # Données utilisateurs connectés
            'user_country_items': user_data['country_items'],
            'user_city_items': user_data['city_items'],
            'user_country_labels': user_data['country_labels'],
            'user_country_data': user_data['country_data'],
            'total_user_pays': user_data['total_pays'],
            'total_user_villes': user_data['total_villes'],
        })
        template = 'ecoles/dashboard_admin.html'

    # --- PROVED ---
    elif user.est_proved():
        province = user.province_affectation
        if not province:
            messages.warning(request, "Vous n'êtes pas affecté à une province.")
            return redirect('ecoles:index')
        ecoles = Ecole.objects.filter(province=province)
        total_ecoles = ecoles.count()
        total_niveaux = Niveau.objects.filter(ecole__in=ecoles, est_reference=False).count()
        total_classes = Classe.objects.filter(ecole__in=ecoles, est_reference=False).count()
        total_cours = Cours.objects.filter(ecole__in=ecoles, est_reference=False).count()
        total_eleves = Eleve.objects.filter(ecole__in=ecoles).count()
        total_notes = EvaluationResultat.objects.filter(annee_scolaire=annee_actuelle, eleve__ecole__in=ecoles).count() if annee_actuelle else 0

        resultats_annuels = ResultatAnnuel.objects.filter(annee_scolaire=annee_actuelle, eleve__ecole__in=ecoles) if annee_actuelle else ResultatAnnuel.objects.none()
        moyenne_province = calculer_moyenne_generale(resultats_annuels)
        taux_reussite_province = calculer_taux_reussite(resultats_annuels)

        stats_par_ecole = []
        for ecole in ecoles:
            res = resultats_annuels.filter(eleve__ecole=ecole)
            if res.exists():
                total = res.count()
                reussis = res.filter(moyenne_generale__gte=10).count()
                taux = (reussis / total * 100) if total > 0 else 0
                stats_par_ecole.append({
                    'nom': ecole.nom,
                    'total': total,
                    'reussis': reussis,
                    'taux': round(taux, 1)
                })
        stats_par_ecole = sorted(stats_par_ecole, key=lambda x: x['taux'], reverse=True)

        context.update({
            'role': 'proved',
            'province_nom': province.nom,
            'total_ecoles': total_ecoles,
            'total_niveaux': total_niveaux,
            'total_classes': total_classes,
            'total_cours': total_cours,
            'total_eleves': total_eleves,
            'total_notes': total_notes,
            'moyenne_province': moyenne_province,
            'taux_reussite_province': taux_reussite_province,
            'stats_par_ecole': stats_par_ecole,
        })
        template = 'ecoles/dashboard_proved.html'

    # --- AGENT / INSPECTEUR ---
    elif user.est_agent() or user.est_inspecteur():
        ecole = user.ecole_affectation
        if not ecole:
            messages.warning(request, "Vous n'êtes pas affecté à une école.")
            return redirect('ecoles:index')
        total_niveaux = Niveau.objects.filter(ecole=ecole, est_reference=False).count()
        total_classes = Classe.objects.filter(ecole=ecole, est_reference=False).count()
        total_cours = Cours.objects.filter(ecole=ecole, est_reference=False).count()
        total_eleves = Eleve.objects.filter(ecole=ecole).count()
        total_notes = EvaluationResultat.objects.filter(annee_scolaire=annee_actuelle, eleve__ecole=ecole).count() if annee_actuelle else 0

        resultats_annuels = ResultatAnnuel.objects.filter(annee_scolaire=annee_actuelle, eleve__ecole=ecole) if annee_actuelle else ResultatAnnuel.objects.none()
        moyenne_ecole = calculer_moyenne_generale(resultats_annuels)
        taux_reussite_ecole = calculer_taux_reussite(resultats_annuels)

        stats_par_classe = []
        for cls in Classe.objects.filter(ecole=ecole, est_reference=False):
            res = resultats_annuels.filter(eleve__classe=cls)
            if res.exists():
                total = res.count()
                reussis = res.filter(moyenne_generale__gte=10).count()
                taux = (reussis / total * 100) if total > 0 else 0
                stats_par_classe.append({
                    'nom': cls.nom,
                    'total': total,
                    'reussis': reussis,
                    'taux': round(taux, 1)
                })
        stats_par_classe = sorted(stats_par_classe, key=lambda x: x['taux'], reverse=True)

        context.update({
            'role': 'agent',
            'ecole_nom': ecole.nom,
            'total_niveaux': total_niveaux,
            'total_classes': total_classes,
            'total_cours': total_cours,
            'total_eleves': total_eleves,
            'total_notes': total_notes,
            'moyenne_ecole': moyenne_ecole,
            'taux_reussite_ecole': taux_reussite_ecole,
            'stats_par_classe': stats_par_classe,
        })
        template = 'ecoles/dashboard_agent.html'

    # --- ENSEIGNANT ---
    elif user.est_enseignant():
        classe = user.classe_affectation
        if not classe:
            messages.warning(request, "Vous n'êtes pas affecté à une classe.")
            return redirect('ecoles:index')
        total_eleves = Eleve.objects.filter(classe=classe).count()
        total_cours = Cours.objects.filter(classe=classe, est_reference=False).count()
        total_notes = EvaluationResultat.objects.filter(annee_scolaire=annee_actuelle, eleve__classe=classe).count() if annee_actuelle else 0

        resultats_annuels = ResultatAnnuel.objects.filter(annee_scolaire=annee_actuelle, eleve__classe=classe) if annee_actuelle else ResultatAnnuel.objects.none()
        moyenne_classe = calculer_moyenne_generale(resultats_annuels)
        taux_reussite_classe = calculer_taux_reussite(resultats_annuels)

        eleves_moyennes = []
        for eleve in Eleve.objects.filter(classe=classe):
            res = ResultatAnnuel.objects.filter(eleve=eleve, annee_scolaire=annee_actuelle).first()
            if res and res.moyenne_generale is not None:
                eleves_moyennes.append({
                    'nom': eleve.get_nom_complet(),
                    'moyenne': float(res.moyenne_generale)
                })
        eleves_moyennes = sorted(eleves_moyennes, key=lambda x: x['moyenne'], reverse=True)

        context.update({
            'role': 'enseignant',
            'classe_nom': classe.nom,
            'total_eleves': total_eleves,
            'total_cours': total_cours,
            'total_notes': total_notes,
            'moyenne_classe': moyenne_classe,
            'taux_reussite_classe': taux_reussite_classe,
            'eleves_moyennes': eleves_moyennes,
        })
        template = 'ecoles/dashboard_enseignant.html'

    # --- PARENT ---
    elif user.est_parent():
        return redirect('ecoles:parent_recherche')

    else:
        messages.warning(request, "Rôle non reconnu.")
        return redirect('ecoles:index')

    return render(request, template, context)


# ===================== RECHERCHE PARENT =====================
@login_required
def parent_recherche(request):
    if not request.user.est_parent():
        messages.error(request, "Accès réservé aux parents.")
        return redirect('ecoles:dashboard')

    annee_id = request.GET.get('annee')
    periode = request.GET.get('periode')
    nom_eleve = request.GET.get('nom_eleve', '').strip()
    resultats = None
    eleve_trouve = None
    annee_scolaire = None

    if annee_id:
        try:
            annee_scolaire = AnneeScolaire.objects.get(pk=annee_id)
        except AnneeScolaire.DoesNotExist:
            messages.error(request, "Année invalide.")
    else:
        annee_scolaire = get_annee_actuelle()

    if nom_eleve and annee_scolaire:
        eleves = Eleve.objects.filter(
            Q(nom__icontains=nom_eleve) |
            Q(prenom__icontains=nom_eleve) |
            Q(postnom__icontains=nom_eleve)
        )
        if eleves.count() == 1:
            eleve_trouve = eleves.first()
            resultat_annuel = ResultatAnnuel.objects.filter(eleve=eleve_trouve, annee_scolaire=annee_scolaire).first()
            if resultat_annuel:
                # ... (code existant, inchangé)
                pass
            else:
                messages.warning(request, "Aucun résultat trouvé pour cet élève cette année.")
        elif eleves.count() > 1:
            messages.warning(request, "Plusieurs élèves correspondent, précisez votre recherche.")
        else:
            messages.warning(request, "Aucun élève trouvé avec ce nom.")

    context = {
        'annee_scolaire': annee_scolaire,
        'annees': AnneeScolaire.objects.all().order_by('-annee'),
        'nom_eleve': nom_eleve,
        'periode': periode,
        'resultats': resultats,
        'eleve_trouve': eleve_trouve,
    }
    return render(request, 'ecoles/parent_recherche.html', context)

# ===================== CRUD PROVINCES =====================
@login_required
def province_list(request):
    if not request.user.est_administrateur():
        messages.error(request, 'Accès non autorisé.')
        return redirect('ecoles:dashboard')
    provinces = Province.objects.all().order_by('nom')
    paginator = Paginator(provinces, 20)
    page = request.GET.get('page')
    provinces = paginator.get_page(page)
    return render(request, 'ecoles/province_list.html', {'provinces': provinces})

@login_required
def province_create(request):
    if not request.user.est_administrateur():
        messages.error(request, 'Accès non autorisé.')
        return redirect('ecoles:dashboard')
    if request.method == 'POST':
        form = ProvinceForm(request.POST)
        if form.is_valid():
            province = form.save()
            messages.success(request, f'Province {province.nom} créée avec succès.')
            return redirect('ecoles:province_list')
    else:
        form = ProvinceForm()
    return render(request, 'ecoles/province_form.html', {'form': form, 'title': 'Créer une province'})

@login_required
def province_edit(request, pk):
    if not request.user.est_administrateur():
        messages.error(request, 'Accès non autorisé.')
        return redirect('ecoles:dashboard')
    province = get_object_or_404(Province, pk=pk)
    if request.method == 'POST':
        form = ProvinceForm(request.POST, instance=province)
        if form.is_valid():
            form.save()
            messages.success(request, 'Province modifiée avec succès.')
            return redirect('ecoles:province_list')
    else:
        form = ProvinceForm(instance=province)
    return render(request, 'ecoles/province_form.html', {'form': form, 'title': 'Modifier une province'})

@login_required
def province_delete(request, pk):
    if not request.user.est_administrateur():
        messages.error(request, 'Accès non autorisé.')
        return redirect('ecoles:dashboard')
    province = get_object_or_404(Province, pk=pk)
    if request.method == 'POST':
        nom = province.nom
        province.delete()
        messages.success(request, f'Province {nom} supprimée avec succès.')
        return redirect('ecoles:province_list')
    return render(request, 'ecoles/province_confirm_delete.html', {'province': province})

# ===================== CRUD ÉCOLES =====================
@login_required
def ecole_list(request):
    user = request.user
    if user.est_parent():
        messages.warning(request, "Vous n'avez pas accès à cette liste.")
        return redirect('ecoles:dashboard')
    elif user.est_enseignant():
        ecoles = Ecole.objects.filter(id=user.ecole_affectation.id) if user.ecole_affectation else Ecole.objects.none()
    elif user.est_agent() or user.est_inspecteur():
        ecoles = Ecole.objects.filter(id=user.ecole_affectation.id) if user.ecole_affectation else Ecole.objects.none()
    elif user.est_proved():
        if user.province_affectation:
            ecoles = Ecole.objects.filter(province=user.province_affectation)
        else:
            ecoles = Ecole.objects.none()
    else:
        ecoles = Ecole.objects.all()
    paginator = Paginator(ecoles, 20)
    page = request.GET.get('page')
    ecoles = paginator.get_page(page)
    return render(request, 'ecoles/ecole_list.html', {'ecoles': ecoles})

@login_required
def ecole_create(request):
    if not request.user.est_administrateur():
        messages.error(request, 'Vous n\'avez pas les droits.')
        return redirect('ecoles:dashboard')
    if request.method == 'POST':
        form = EcoleForm(request.POST, user=request.user)
        if form.is_valid():
            ecole = form.save()
            niveaux_ref = form.cleaned_data.get('niveaux_reference')
            if niveaux_ref:
                for niveau_ref in niveaux_ref:
                    try:
                        niveau_ref.affecter_a_ecole(ecole)
                    except Exception as e:
                        messages.warning(request, f'Erreur lors de l\'affectation du niveau {niveau_ref.nom}: {str(e)}')
            messages.success(request, f'École {ecole.nom} créée avec succès.')
            return redirect('ecoles:ecole_list')
    else:
        form = EcoleForm(user=request.user)
    return render(request, 'ecoles/ecole_form.html', {'form': form, 'title': 'Créer une école'})

@login_required
def ecole_edit(request, pk):
    ecole = get_object_or_404(Ecole, pk=pk)
    if not request.user.est_administrateur():
        messages.error(request, 'Accès non autorisé.')
        return redirect('ecoles:dashboard')
    if request.method == 'POST':
        form = EcoleForm(request.POST, instance=ecole, user=request.user)
        if form.is_valid():
            ecole = form.save()
            niveaux_ref = form.cleaned_data.get('niveaux_reference')
            if niveaux_ref:
                for niveau_ref in niveaux_ref:
                    if not Niveau.objects.filter(nom=niveau_ref.nom, ecole=ecole, est_reference=False).exists():
                        try:
                            niveau_ref.affecter_a_ecole(ecole)
                            messages.success(request, f'Niveau {niveau_ref.nom} attribué avec succès.')
                        except Exception as e:
                            messages.warning(request, f'Erreur lors de l\'attribution du niveau {niveau_ref.nom}: {str(e)}')
            messages.success(request, 'École modifiée avec succès.')
            return redirect('ecoles:ecole_list')
    else:
        form = EcoleForm(instance=ecole, user=request.user)
        niveaux_attribues = ecole.niveaux.all()
        return render(request, 'ecoles/ecole_form.html', {
            'form': form,
            'title': 'Modifier une école',
            'niveaux_attribues': niveaux_attribues
        })

@login_required
def ecole_delete(request, pk):
    ecole = get_object_or_404(Ecole, pk=pk)
    if not request.user.est_administrateur():
        messages.error(request, 'Accès non autorisé.')
        return redirect('ecoles:dashboard')
    if request.method == 'POST':
        nom = ecole.nom
        ecole.delete()
        messages.success(request, f'École {nom} supprimée avec succès.')
        return redirect('ecoles:ecole_list')
    return render(request, 'ecoles/ecole_confirm_delete.html', {'ecole': ecole})

# ===================== CRUD NIVEAUX =====================
@login_required
def niveau_list(request):
    user = request.user
    if user.est_parent():
        messages.warning(request, "Vous n'avez pas accès à cette liste.")
        return redirect('ecoles:dashboard')
    elif user.est_enseignant():
        niveaux = Niveau.objects.filter(ecole=user.ecole_affectation, est_reference=False) if user.ecole_affectation else Niveau.objects.none()
    elif user.est_agent() or user.est_inspecteur():
        niveaux = Niveau.objects.filter(ecole=user.ecole_affectation, est_reference=False) if user.ecole_affectation else Niveau.objects.none()
    elif user.est_proved():
        if user.province_affectation:
            ecoles = Ecole.objects.filter(province=user.province_affectation)
            niveaux = Niveau.objects.filter(ecole__in=ecoles, est_reference=False)
        else:
            niveaux = Niveau.objects.none()
    else:
        niveaux = Niveau.objects.all().order_by('-est_reference', 'nom')
    paginator = Paginator(niveaux, 20)
    page = request.GET.get('page')
    niveaux = paginator.get_page(page)
    return render(request, 'ecoles/niveau_list.html', {'niveaux': niveaux})

@login_required
def niveau_create(request):
    if not request.user.est_administrateur():
        messages.error(request, 'Seuls les administrateurs peuvent créer des niveaux de référence.')
        return redirect('ecoles:dashboard')
    if request.method == 'POST':
        form = NiveauForm(request.POST, user=request.user, is_reference=True)
        form.instance.est_reference = True
        if form.is_valid():
            niveau = form.save(commit=False)
            niveau.ecole = None
            niveau.save()
            messages.success(request, f'Niveau de référence {niveau.nom} créé avec succès.')
            return redirect('ecoles:niveau_list')
    else:
        form = NiveauForm(user=request.user, is_reference=True)
        form.instance.est_reference = True
    return render(request, 'ecoles/niveau_form.html', {'form': form, 'title': 'Créer un niveau de référence'})

@login_required
def niveau_edit(request, pk):
    niveau = get_object_or_404(Niveau, pk=pk)
    user = request.user
    if user.est_parent():
        messages.error(request, 'Accès non autorisé.')
        return redirect('ecoles:dashboard')
    if niveau.est_reference:
        if not user.est_administrateur():
            messages.error(request, 'Accès non autorisé.')
            return redirect('ecoles:dashboard')
        is_reference = True
    else:
        if user.est_agent() and niveau.ecole != user.ecole_affectation:
            messages.error(request, 'Accès non autorisé.')
            return redirect('ecoles:dashboard')
        if user.est_proved() and (niveau.ecole and niveau.ecole.province != user.province_affectation):
            messages.error(request, 'Accès non autorisé.')
            return redirect('ecoles:dashboard')
        is_reference = False

    if request.method == 'POST':
        form = NiveauForm(request.POST, instance=niveau, user=user, is_reference=is_reference)
        if form.is_valid():
            form.save()
            messages.success(request, 'Niveau modifié avec succès.')
            return redirect('ecoles:niveau_list')
    else:
        form = NiveauForm(instance=niveau, user=user, is_reference=is_reference)
    return render(request, 'ecoles/niveau_form.html', {'form': form, 'title': 'Modifier un niveau'})

@login_required
def niveau_delete(request, pk):
    niveau = get_object_or_404(Niveau, pk=pk)
    user = request.user
    if user.est_parent():
        messages.error(request, 'Accès non autorisé.')
        return redirect('ecoles:dashboard')
    if niveau.est_reference:
        if not user.est_administrateur():
            messages.error(request, 'Accès non autorisé.')
            return redirect('ecoles:dashboard')
    else:
        if user.est_agent() and niveau.ecole != user.ecole_affectation:
            messages.error(request, 'Accès non autorisé.')
            return redirect('ecoles:dashboard')
        if user.est_proved() and (niveau.ecole and niveau.ecole.province != user.province_affectation):
            messages.error(request, 'Accès non autorisé.')
            return redirect('ecoles:dashboard')
    if request.method == 'POST':
        nom = niveau.nom
        niveau.delete()
        messages.success(request, f'Niveau {nom} supprimé avec succès.')
        return redirect('ecoles:niveau_list')
    return render(request, 'ecoles/niveau_confirm_delete.html', {'niveau': niveau})

@login_required
def niveau_affecter_ecole(request, pk):
    niveau_ref = get_object_or_404(Niveau, pk=pk, est_reference=True, ecole=None)
    user = request.user
    if user.est_parent():
        messages.error(request, 'Accès non autorisé.')
        return redirect('ecoles:niveau_list')
    if not user.est_agent() and not user.est_enseignant():
        messages.error(request, 'Vous devez être agent ou enseignant pour affecter un niveau à votre école.')
        return redirect('ecoles:niveau_list')
    ecole = user.ecole_affectation
    if not ecole:
        messages.error(request, 'Vous n\'êtes pas rattaché à une école.')
        return redirect('ecoles:niveau_list')

    if request.method == 'POST':
        try:
            niveau_ref.affecter_a_ecole(ecole)
            messages.success(request, f'Le niveau {niveau_ref.nom} a été affecté à {ecole.nom} avec toutes ses classes et cours.')
        except Exception as e:
            messages.error(request, f'Erreur : {str(e)}')
        return redirect('ecoles:niveau_list')

    return render(request, 'ecoles/niveau_affecter.html', {
        'niveau': niveau_ref,
        'ecole': ecole
    })

# ===================== CRUD CLASSES =====================
@login_required
def classe_list(request):
    user = request.user
    if user.est_parent():
        messages.warning(request, "Vous n'avez pas accès à cette liste.")
        return redirect('ecoles:dashboard')
    elif user.est_enseignant():
        if user.classe_affectation:
            classes = Classe.objects.filter(id=user.classe_affectation.id, est_reference=False)
        else:
            classes = Classe.objects.none()
    elif user.est_agent() or user.est_inspecteur():
        classes = Classe.objects.filter(ecole=user.ecole_affectation, est_reference=False) if user.ecole_affectation else Classe.objects.none()
    elif user.est_proved():
        if user.province_affectation:
            ecoles = Ecole.objects.filter(province=user.province_affectation)
            classes = Classe.objects.filter(ecole__in=ecoles, est_reference=False)
        else:
            classes = Classe.objects.none()
    else:
        classes = Classe.objects.all().order_by('-est_reference', 'nom')
    paginator = Paginator(classes, 20)
    page = request.GET.get('page')
    classes = paginator.get_page(page)
    return render(request, 'ecoles/classe_list.html', {'classes': classes})

@login_required
def classe_create(request):
    if not request.user.est_administrateur():
        messages.error(request, 'Seuls les administrateurs peuvent créer des classes de référence.')
        return redirect('ecoles:dashboard')
    if request.method == 'POST':
        form = ClasseForm(request.POST, user=request.user, is_reference=True)
        form.instance.est_reference = True
        if form.is_valid():
            classe = form.save(commit=False)
            classe.ecole = None
            classe.save()
            messages.success(request, f'Classe de référence {classe.nom} créée avec succès.')
            return redirect('ecoles:classe_list')
    else:
        form = ClasseForm(user=request.user, is_reference=True)
        form.instance.est_reference = True
    return render(request, 'ecoles/classe_form.html', {'form': form, 'title': 'Créer une classe de référence'})

@login_required
def classe_edit(request, pk):
    classe = get_object_or_404(Classe, pk=pk)
    user = request.user
    if user.est_parent():
        messages.error(request, 'Accès non autorisé.')
        return redirect('ecoles:dashboard')
    if classe.est_reference:
        if not user.est_administrateur():
            messages.error(request, 'Accès non autorisé.')
            return redirect('ecoles:dashboard')
        is_reference = True
    else:
        if user.est_agent() and classe.ecole != user.ecole_affectation:
            messages.error(request, 'Accès non autorisé.')
            return redirect('ecoles:dashboard')
        if user.est_proved() and (classe.ecole and classe.ecole.province != user.province_affectation):
            messages.error(request, 'Accès non autorisé.')
            return redirect('ecoles:dashboard')
        is_reference = False
    if request.method == 'POST':
        form = ClasseForm(request.POST, instance=classe, user=user, is_reference=is_reference)
        if form.is_valid():
            form.save()
            messages.success(request, 'Classe modifiée avec succès.')
            return redirect('ecoles:classe_list')
    else:
        form = ClasseForm(instance=classe, user=user, is_reference=is_reference)
    return render(request, 'ecoles/classe_form.html', {'form': form, 'title': 'Modifier une classe'})

@login_required
def classe_delete(request, pk):
    classe = get_object_or_404(Classe, pk=pk)
    user = request.user
    if user.est_parent():
        messages.error(request, 'Accès non autorisé.')
        return redirect('ecoles:dashboard')
    if classe.est_reference:
        if not user.est_administrateur():
            messages.error(request, 'Accès non autorisé.')
            return redirect('ecoles:dashboard')
    else:
        if user.est_agent() and classe.ecole != user.ecole_affectation:
            messages.error(request, 'Accès non autorisé.')
            return redirect('ecoles:dashboard')
        if user.est_proved() and (classe.ecole and classe.ecole.province != user.province_affectation):
            messages.error(request, 'Accès non autorisé.')
            return redirect('ecoles:dashboard')
    if request.method == 'POST':
        nom = classe.nom
        classe.delete()
        messages.success(request, f'Classe {nom} supprimée avec succès.')
        return redirect('ecoles:classe_list')
    return render(request, 'ecoles/classe_confirm_delete.html', {'classe': classe})

# ===================== CRUD DOMAINES =====================
@login_required
def domaine_list(request):
    user = request.user
    if user.est_parent():
        messages.warning(request, "Vous n'avez pas accès à cette liste.")
        return redirect('ecoles:dashboard')
    elif user.est_enseignant():
        domaines = Domaine.objects.filter(ecole=user.ecole_affectation, est_reference=False) if user.ecole_affectation else Domaine.objects.none()
    elif user.est_agent() or user.est_inspecteur():
        domaines = Domaine.objects.filter(ecole=user.ecole_affectation, est_reference=False) if user.ecole_affectation else Domaine.objects.none()
    elif user.est_proved():
        if user.province_affectation:
            ecoles = Ecole.objects.filter(province=user.province_affectation)
            domaines = Domaine.objects.filter(ecole__in=ecoles, est_reference=False)
        else:
            domaines = Domaine.objects.none()
    else:
        domaines = Domaine.objects.all().order_by('-est_reference', 'nom')
    paginator = Paginator(domaines, 20)
    page = request.GET.get('page')
    domaines = paginator.get_page(page)
    return render(request, 'ecoles/domaine_list.html', {'domaines': domaines})

@login_required
def domaine_create(request):
    if not request.user.est_administrateur():
        messages.error(request, 'Seuls les administrateurs peuvent créer des domaines de référence.')
        return redirect('ecoles:dashboard')
    if request.method == 'POST':
        form = DomaineForm(request.POST, user=request.user, is_reference=True)
        form.instance.est_reference = True
        if form.is_valid():
            domaine = form.save(commit=False)
            domaine.ecole = None
            domaine.save()
            form.save_m2m()
            messages.success(request, f'Domaine de référence {domaine.nom} créé avec succès.')
            return redirect('ecoles:domaine_list')
    else:
        form = DomaineForm(user=request.user, is_reference=True)
        form.instance.est_reference = True
    return render(request, 'ecoles/domaine_form.html', {'form': form, 'title': 'Créer un domaine de référence'})

@login_required
def domaine_edit(request, pk):
    domaine = get_object_or_404(Domaine, pk=pk)
    user = request.user
    if user.est_parent():
        messages.error(request, 'Accès non autorisé.')
        return redirect('ecoles:dashboard')
    if domaine.est_reference:
        if not user.est_administrateur():
            messages.error(request, 'Accès non autorisé.')
            return redirect('ecoles:dashboard')
    else:
        if user.est_agent() and domaine.ecole != user.ecole_affectation:
            messages.error(request, 'Accès non autorisé.')
            return redirect('ecoles:dashboard')
        if user.est_proved() and (domaine.ecole and domaine.ecole.province != user.province_affectation):
            messages.error(request, 'Accès non autorisé.')
            return redirect('ecoles:dashboard')
    if request.method == 'POST':
        form = DomaineForm(request.POST, instance=domaine, user=user, is_reference=domaine.est_reference)
        if form.is_valid():
            domaine = form.save()
            messages.success(request, 'Domaine modifié avec succès.')
            return redirect('ecoles:domaine_list')
    else:
        form = DomaineForm(instance=domaine, user=user, is_reference=domaine.est_reference)
    return render(request, 'ecoles/domaine_form.html', {'form': form, 'title': 'Modifier un domaine'})

@login_required
def domaine_delete(request, pk):
    domaine = get_object_or_404(Domaine, pk=pk)
    user = request.user
    if user.est_parent():
        messages.error(request, 'Accès non autorisé.')
        return redirect('ecoles:dashboard')
    if domaine.est_reference:
        if not user.est_administrateur():
            messages.error(request, 'Accès non autorisé.')
            return redirect('ecoles:dashboard')
    else:
        if user.est_agent() and domaine.ecole != user.ecole_affectation:
            messages.error(request, 'Accès non autorisé.')
            return redirect('ecoles:dashboard')
        if user.est_proved() and (domaine.ecole and domaine.ecole.province != user.province_affectation):
            messages.error(request, 'Accès non autorisé.')
            return redirect('ecoles:dashboard')
    if request.method == 'POST':
        nom = domaine.nom
        domaine.delete()
        messages.success(request, f'Domaine {nom} supprimé avec succès.')
        return redirect('ecoles:domaine_list')
    return render(request, 'ecoles/domaine_confirm_delete.html', {'domaine': domaine})

# ===================== CRUD COURS =====================
@login_required
def cours_list(request):
    user = request.user
    if user.est_parent():
        messages.warning(request, "Vous n'avez pas accès à cette liste.")
        return redirect('ecoles:dashboard')
    elif user.est_enseignant():
        if user.classe_affectation:
            cours_qs = Cours.objects.filter(classe=user.classe_affectation, est_reference=False)
        else:
            cours_qs = Cours.objects.none()
    elif user.est_agent() or user.est_inspecteur():
        cours_qs = Cours.objects.filter(ecole=user.ecole_affectation, est_reference=False) if user.ecole_affectation else Cours.objects.none()
    elif user.est_proved():
        if user.province_affectation:
            ecoles = Ecole.objects.filter(province=user.province_affectation)
            cours_qs = Cours.objects.filter(ecole__in=ecoles, est_reference=False)
        else:
            cours_qs = Cours.objects.none()
    else:
        cours_qs = Cours.objects.all().order_by('-est_reference', 'nom')

    ecole_id = request.GET.get('ecole')
    niveau_id = request.GET.get('niveau')
    classe_id = request.GET.get('classe')
    domaine_id = request.GET.get('domaine')

    if ecole_id:
        cours_qs = cours_qs.filter(ecole_id=ecole_id, est_reference=False)
    if niveau_id:
        cours_qs = cours_qs.filter(niveau_id=niveau_id)
    if classe_id:
        cours_qs = cours_qs.filter(classe_id=classe_id)
    if domaine_id:
        cours_qs = cours_qs.filter(domaine_id=domaine_id)

    paginator = Paginator(cours_qs, 20)
    page = request.GET.get('page')
    cours = paginator.get_page(page)

    if user.est_enseignant():
        ecoles = Ecole.objects.filter(id=user.ecole_affectation.id) if user.ecole_affectation else Ecole.objects.none()
        niveaux = Niveau.objects.filter(ecole=user.ecole_affectation, est_reference=False) if user.ecole_affectation else Niveau.objects.none()
        classes = Classe.objects.filter(id=user.classe_affectation.id) if user.classe_affectation else Classe.objects.none()
        domaines = Domaine.objects.filter(ecole=user.ecole_affectation, est_reference=False) if user.ecole_affectation else Domaine.objects.none()
    elif user.est_agent() or user.est_inspecteur():
        ecoles = Ecole.objects.filter(id=user.ecole_affectation.id) if user.ecole_affectation else Ecole.objects.none()
        niveaux = Niveau.objects.filter(ecole=user.ecole_affectation, est_reference=False) if user.ecole_affectation else Niveau.objects.none()
        classes = Classe.objects.filter(ecole=user.ecole_affectation, est_reference=False) if user.ecole_affectation else Classe.objects.none()
        domaines = Domaine.objects.filter(ecole=user.ecole_affectation, est_reference=False) if user.ecole_affectation else Domaine.objects.none()
    elif user.est_proved():
        if user.province_affectation:
            ecoles = Ecole.objects.filter(province=user.province_affectation)
            niveaux = Niveau.objects.filter(ecole__in=ecoles, est_reference=False)
            classes = Classe.objects.filter(ecole__in=ecoles, est_reference=False)
            domaines = Domaine.objects.filter(ecole__in=ecoles, est_reference=False)
        else:
            ecoles = Ecole.objects.none()
            niveaux = Niveau.objects.none()
            classes = Classe.objects.none()
            domaines = Domaine.objects.none()
    else:
        ecoles = Ecole.objects.all()
        niveaux = Niveau.objects.filter(est_reference=False)
        classes = Classe.objects.filter(est_reference=False)
        domaines = Domaine.objects.filter(est_reference=False)

    context = {
        'cours': cours,
        'ecoles': ecoles,
        'niveaux': niveaux,
        'classes': classes,
        'domaines': domaines,
        'selected_ecole': ecole_id,
        'selected_niveau': niveau_id,
        'selected_classe': classe_id,
        'selected_domaine': domaine_id,
    }
    return render(request, 'ecoles/cours_list.html', context)

@login_required
def cours_create(request):
    if not request.user.est_administrateur():
        messages.error(request, 'Seuls les administrateurs peuvent créer des cours de référence.')
        return redirect('ecoles:dashboard')
    if request.method == 'POST':
        form = CoursForm(request.POST, user=request.user, is_reference=True)
        form.instance.est_reference = True
        if form.is_valid():
            cours = form.save(commit=False)
            cours.ecole = None
            cours.save()
            CycleEvaluation.objects.create(cours=cours, type_cycle='trimestre')
            messages.success(request, f'Cours de référence {cours.nom} créé avec succès.')
            return redirect('ecoles:cours_list')
    else:
        form = CoursForm(user=request.user, is_reference=True)
        form.instance.est_reference = True
    return render(request, 'ecoles/cours_form.html', {'form': form, 'title': 'Créer un cours de référence'})

@login_required
def cours_edit(request, pk):
    cours = get_object_or_404(Cours, pk=pk)
    user = request.user
    if user.est_parent():
        messages.error(request, 'Accès non autorisé.')
        return redirect('ecoles:dashboard')
    if cours.est_reference:
        if not user.est_administrateur():
            messages.error(request, 'Accès non autorisé.')
            return redirect('ecoles:dashboard')
        is_reference = True
    else:
        if user.est_agent() and cours.ecole != user.ecole_affectation:
            messages.error(request, 'Accès non autorisé.')
            return redirect('ecoles:dashboard')
        if user.est_proved() and (cours.ecole and cours.ecole.province != user.province_affectation):
            messages.error(request, 'Accès non autorisé.')
            return redirect('ecoles:dashboard')
        is_reference = False

    cycle_eval, created = CycleEvaluation.objects.get_or_create(cours=cours)
    if request.method == 'POST':
        form = CoursForm(request.POST, instance=cours, user=user, is_reference=is_reference)
        cycle_form = CycleEvaluationForm(request.POST, instance=cycle_eval)
        formset = EvaluationConfigFormSet(request.POST, instance=cycle_eval)
        if form.is_valid() and cycle_form.is_valid() and formset.is_valid():
            form.save()
            cycle_form.save()
            formset.save()
            messages.success(request, 'Cours modifié avec succès.')
            return redirect('ecoles:cours_list')
    else:
        form = CoursForm(instance=cours, user=user, is_reference=is_reference)
        cycle_form = CycleEvaluationForm(instance=cycle_eval)
        formset = EvaluationConfigFormSet(instance=cycle_eval)
    context = {
        'form': form,
        'cycle_form': cycle_form,
        'formset': formset,
        'cours': cours,
        'title': 'Modifier un cours'
    }
    return render(request, 'ecoles/cours_form.html', context)

@login_required
def cours_delete(request, pk):
    cours = get_object_or_404(Cours, pk=pk)
    user = request.user
    if user.est_parent():
        messages.error(request, 'Accès non autorisé.')
        return redirect('ecoles:dashboard')
    if cours.est_reference:
        if not user.est_administrateur():
            messages.error(request, 'Accès non autorisé.')
            return redirect('ecoles:dashboard')
    else:
        if user.est_agent() and cours.ecole != user.ecole_affectation:
            messages.error(request, 'Accès non autorisé.')
            return redirect('ecoles:dashboard')
        if user.est_proved() and (cours.ecole and cours.ecole.province != user.province_affectation):
            messages.error(request, 'Accès non autorisé.')
            return redirect('ecoles:dashboard')
    if request.method == 'POST':
        nom = cours.nom
        cours.delete()
        messages.success(request, f'Cours {nom} supprimé avec succès.')
        return redirect('ecoles:cours_list')
    return render(request, 'ecoles/cours_confirm_delete.html', {'cours': cours})

# ===================== CRUD ANNÉES SCOLAIRES =====================
@login_required
def annee_list(request):
    if not request.user.est_administrateur():
        messages.error(request, 'Accès non autorisé.')
        return redirect('ecoles:dashboard')
    annees = AnneeScolaire.objects.all().order_by('-annee')
    paginator = Paginator(annees, 20)
    page = request.GET.get('page')
    annees = paginator.get_page(page)
    return render(request, 'ecoles/annee_list.html', {'annees': annees})

@login_required
def annee_create(request):
    if not request.user.est_administrateur():
        messages.error(request, 'Accès non autorisé.')
        return redirect('ecoles:dashboard')
    if request.method == 'POST':
        form = AnneeScolaireForm(request.POST)
        if form.is_valid():
            annee = form.save()
            messages.success(request, f'Année {annee.annee} créée avec succès.')
            return redirect('ecoles:annee_list')
    else:
        form = AnneeScolaireForm()
    return render(request, 'ecoles/annee_form.html', {'form': form, 'title': 'Créer une année'})

@login_required
def annee_edit(request, pk):
    if not request.user.est_administrateur():
        messages.error(request, 'Accès non autorisé.')
        return redirect('ecoles:dashboard')
    annee = get_object_or_404(AnneeScolaire, pk=pk)
    if request.method == 'POST':
        form = AnneeScolaireForm(request.POST, instance=annee)
        if form.is_valid():
            form.save()
            messages.success(request, 'Année modifiée avec succès.')
            return redirect('ecoles:annee_list')
    else:
        form = AnneeScolaireForm(instance=annee)
    return render(request, 'ecoles/annee_form.html', {'form': form, 'title': 'Modifier une année'})

@login_required
def annee_delete(request, pk):
    if not request.user.est_administrateur():
        messages.error(request, 'Accès non autorisé.')
        return redirect('ecoles:dashboard')
    annee = get_object_or_404(AnneeScolaire, pk=pk)
    if request.method == 'POST':
        nom = annee.annee
        annee.delete()
        messages.success(request, f'Année {nom} supprimée avec succès.')
        return redirect('ecoles:annee_list')
    return render(request, 'ecoles/annee_confirm_delete.html', {'annee': annee})

# ===================== RÉSULTATS =====================
@login_required
def resultat_list(request):
    user = request.user
    resultats = EvaluationResultat.objects.all()
    if user.est_parent():
        messages.warning(request, "Vous n'avez pas accès à cette liste.")
        return redirect('ecoles:dashboard')
    elif user.est_enseignant():
        if user.classe_affectation:
            resultats = resultats.filter(eleve__classe=user.classe_affectation)
        else:
            resultats = resultats.none()
    elif user.est_agent() or user.est_inspecteur():
        resultats = resultats.filter(eleve__ecole=user.ecole_affectation) if user.ecole_affectation else resultats.none()
    elif user.est_proved():
        if user.province_affectation:
            ecoles = Ecole.objects.filter(province=user.province_affectation)
            resultats = resultats.filter(eleve__ecole__in=ecoles)
        else:
            resultats = resultats.none()

    ecole_id = request.GET.get('ecole')
    niveau_id = request.GET.get('niveau')
    classe_id = request.GET.get('classe')
    cours_id = request.GET.get('cours')
    annee_id = request.GET.get('annee')
    statut = request.GET.get('statut')
    sans_note = request.GET.get('sans_note')

    if ecole_id:
        resultats = resultats.filter(eleve__ecole_id=ecole_id)
    if niveau_id:
        resultats = resultats.filter(eleve__niveau_id=niveau_id)
    if classe_id:
        resultats = resultats.filter(eleve__classe_id=classe_id)
    if cours_id:
        resultats = resultats.filter(cours_id=cours_id)
    if annee_id:
        resultats = resultats.filter(annee_scolaire_id=annee_id)

    if statut == 'reussite':
        resultats = resultats.filter(points_obtenus__gte=0.5 * F('evaluation_config__points_max'))
    elif statut == 'echec':
        resultats = resultats.filter(points_obtenus__lt=0.5 * F('evaluation_config__points_max'))

    eleves_sans_note = None
    if sans_note and cours_id and annee_id:
        eleves_avec_note = EvaluationResultat.objects.filter(
            cours_id=cours_id,
            annee_scolaire_id=annee_id
        ).values_list('eleve_id', flat=True).distinct()
        eleves_queryset = Eleve.objects.all()
        if user.est_enseignant() and user.classe_affectation:
            eleves_queryset = eleves_queryset.filter(classe=user.classe_affectation)
        elif user.est_agent() or user.est_inspecteur():
            eleves_queryset = eleves_queryset.filter(ecole=user.ecole_affectation)
        elif user.est_proved() and user.province_affectation:
            ecoles = Ecole.objects.filter(province=user.province_affectation)
            eleves_queryset = eleves_queryset.filter(ecole__in=ecoles)
        if ecole_id:
            eleves_queryset = eleves_queryset.filter(ecole_id=ecole_id)
        if niveau_id:
            eleves_queryset = eleves_queryset.filter(niveau_id=niveau_id)
        if classe_id:
            eleves_queryset = eleves_queryset.filter(classe_id=classe_id)
        eleves_sans_note = eleves_queryset.exclude(id__in=eleves_avec_note)

    paginator = Paginator(resultats, 20)
    page = request.GET.get('page')
    resultats_page = paginator.get_page(page)

    if user.est_enseignant():
        ecoles = Ecole.objects.filter(id=user.ecole_affectation.id) if user.ecole_affectation else Ecole.objects.none()
        niveaux = Niveau.objects.filter(ecole=user.ecole_affectation, est_reference=False) if user.ecole_affectation else Niveau.objects.none()
        classes = Classe.objects.filter(id=user.classe_affectation.id) if user.classe_affectation else Classe.objects.none()
        cours = Cours.objects.filter(classe=user.classe_affectation, est_reference=False) if user.classe_affectation else Cours.objects.none()
    elif user.est_agent() or user.est_inspecteur():
        ecoles = Ecole.objects.filter(id=user.ecole_affectation.id) if user.ecole_affectation else Ecole.objects.none()
        niveaux = Niveau.objects.filter(ecole=user.ecole_affectation, est_reference=False) if user.ecole_affectation else Niveau.objects.none()
        classes = Classe.objects.filter(ecole=user.ecole_affectation, est_reference=False) if user.ecole_affectation else Classe.objects.none()
        cours = Cours.objects.filter(ecole=user.ecole_affectation, est_reference=False) if user.ecole_affectation else Cours.objects.none()
    elif user.est_proved():
        if user.province_affectation:
            ecoles = Ecole.objects.filter(province=user.province_affectation)
            niveaux = Niveau.objects.filter(ecole__in=ecoles, est_reference=False)
            classes = Classe.objects.filter(ecole__in=ecoles, est_reference=False)
            cours = Cours.objects.filter(ecole__in=ecoles, est_reference=False)
        else:
            ecoles = Ecole.objects.none()
            niveaux = Niveau.objects.none()
            classes = Classe.objects.none()
            cours = Cours.objects.none()
    else:
        ecoles = Ecole.objects.all()
        niveaux = Niveau.objects.filter(est_reference=False)
        classes = Classe.objects.filter(est_reference=False)
        cours = Cours.objects.filter(est_reference=False)

    context = {
        'resultats': resultats_page,
        'eleves_sans_note': eleves_sans_note,
        'ecoles': ecoles,
        'niveaux': niveaux,
        'classes': classes,
        'cours': cours,
        'annees': AnneeScolaire.objects.all(),
        'selected_ecole': ecole_id,
        'selected_niveau': niveau_id,
        'selected_classe': classe_id,
        'selected_cours': cours_id,
        'selected_annee': annee_id,
    }
    return render(request, 'ecoles/resultat_list.html', context)

@login_required
def resultat_create(request):
    user = request.user
    if user.est_parent():
        messages.error(request, 'Vous n\'avez pas les droits pour saisir des résultats.')
        return redirect('ecoles:resultat_list')
    if request.method == 'GET' and not (request.GET.get('eleve') and request.GET.get('cours') and request.GET.get('annee_scolaire')):
        selection_form = ResultatSelectionForm(user=request.user)
        return render(request, 'ecoles/resultat_form.html', {
            'selection_form': selection_form,
            'title': 'Saisie des résultats'
        })

    eleve_id = request.GET.get('eleve') or request.POST.get('eleve')
    cours_id = request.GET.get('cours') or request.POST.get('cours')
    annee_id = request.GET.get('annee_scolaire') or request.POST.get('annee_scolaire')

    if not all([eleve_id, cours_id, annee_id]):
        messages.error(request, 'Veuillez sélectionner un élève, un cours et une année.')
        return redirect('ecoles:resultat_create')

    try:
        eleve = Eleve.objects.get(pk=eleve_id)
        cours = Cours.objects.get(pk=cours_id)
        annee = AnneeScolaire.objects.get(pk=annee_id)
    except (Eleve.DoesNotExist, Cours.DoesNotExist, AnneeScolaire.DoesNotExist):
        messages.error(request, 'Élément sélectionné invalide.')
        return redirect('ecoles:resultat_create')

    if user.est_enseignant():
        if not user.classe_affectation or eleve.classe != user.classe_affectation:
            messages.error(request, 'Vous ne pouvez saisir que pour votre classe.')
            return redirect('ecoles:resultat_list')
    elif user.est_agent() and (eleve.ecole != user.ecole_affectation or cours.ecole != user.ecole_affectation):
        messages.error(request, 'Accès non autorisé.')
        return redirect('ecoles:dashboard')
    elif user.est_proved() and (eleve.ecole.province != user.province_affectation or cours.ecole.province != user.province_affectation):
        messages.error(request, 'Accès non autorisé.')
        return redirect('ecoles:dashboard')

    if cours.est_reference:
        messages.error(request, 'Vous ne pouvez pas saisir de notes pour un cours de référence.')
        return redirect('ecoles:resultat_list')

    cycle_eval, created = CycleEvaluation.objects.get_or_create(cours=cours)
    if created or not cycle_eval.evaluations.exists():
        cycle_eval.creer_evaluations_par_defaut()
        messages.info(request, f"Les évaluations par défaut ont été créées pour le cours '{cours.nom}'.")

    if request.method == 'POST':
        form = EvaluationResultatForm(eleve, cours, annee, user=request.user, data=request.POST)
        if form.is_valid():
            form.save()
            recalculer_resultats_eleve(eleve, annee)
            messages.success(request, 'Résultats enregistrés avec succès.')
            return redirect('ecoles:resultat_list')
    else:
        form = EvaluationResultatForm(eleve, cours, annee, user=request.user)

    context = {
        'form': form,
        'eleve': eleve,
        'cours': cours,
        'annee': annee,
        'title': 'Saisie des résultats',
    }
    return render(request, 'ecoles/resultat_form.html', context)

@login_required
def resultat_edit(request, pk):
    resultat = get_object_or_404(EvaluationResultat, pk=pk)
    user = request.user
    if user.est_parent():
        messages.error(request, 'Accès non autorisé.')
        return redirect('ecoles:dashboard')
    elif user.est_enseignant():
        if not user.classe_affectation or resultat.eleve.classe != user.classe_affectation:
            messages.error(request, 'Accès non autorisé.')
            return redirect('ecoles:dashboard')
    elif user.est_agent() and resultat.eleve.ecole != user.ecole_affectation:
        messages.error(request, 'Accès non autorisé.')
        return redirect('ecoles:dashboard')
    elif user.est_proved() and (resultat.eleve.ecole.province != user.province_affectation):
        messages.error(request, 'Accès non autorisé.')
        return redirect('ecoles:dashboard')
    url = reverse('ecoles:resultat_create') + f"?eleve={resultat.eleve.id}&cours={resultat.cours.id}&annee_scolaire={resultat.annee_scolaire.id}"
    return redirect(url)

@login_required
def resultat_delete(request, pk):
    resultat = get_object_or_404(EvaluationResultat, pk=pk)
    user = request.user
    if user.est_parent():
        messages.error(request, 'Accès non autorisé.')
        return redirect('ecoles:dashboard')
    elif user.est_enseignant():
        if not user.classe_affectation or resultat.eleve.classe != user.classe_affectation:
            messages.error(request, 'Accès non autorisé.')
            return redirect('ecoles:dashboard')
    elif user.est_agent() and resultat.eleve.ecole != user.ecole_affectation:
        messages.error(request, 'Accès non autorisé.')
        return redirect('ecoles:dashboard')
    elif user.est_proved() and (resultat.eleve.ecole.province != user.province_affectation):
        messages.error(request, 'Accès non autorisé.')
        return redirect('ecoles:dashboard')
    if request.method == 'POST':
        resultat.delete()
        messages.success(request, 'Résultat supprimé avec succès.')
        return redirect('ecoles:resultat_list')
    return render(request, 'ecoles/resultat_confirm_delete.html', {'resultat': resultat})

# ===================== BULLETINS =====================
@login_required
def bulletin_view(request):
    user = request.user
    if user.est_parent():
        messages.warning(request, "Vous n'avez pas accès à cette liste.")
        return redirect('ecoles:dashboard')
    ecole_id = request.GET.get('ecole')
    niveau_id = request.GET.get('niveau')
    classe_id = request.GET.get('classe')
    annee_id = request.GET.get('annee')

    if user.est_enseignant():
        if user.classe_affectation:
            eleves = Eleve.objects.filter(classe=user.classe_affectation)
        else:
            eleves = Eleve.objects.none()
    elif user.est_agent() or user.est_inspecteur():
        eleves = Eleve.objects.filter(ecole=user.ecole_affectation) if user.ecole_affectation else Eleve.objects.none()
    elif user.est_proved():
        if user.province_affectation:
            ecoles = Ecole.objects.filter(province=user.province_affectation)
            eleves = Eleve.objects.filter(ecole__in=ecoles)
        else:
            eleves = Eleve.objects.none()
    else:
        eleves = Eleve.objects.all()

    if ecole_id:
        eleves = eleves.filter(ecole_id=ecole_id)
    if niveau_id:
        eleves = eleves.filter(niveau_id=niveau_id)
    if classe_id:
        eleves = eleves.filter(classe_id=classe_id)
    if annee_id:
        eleves = eleves.filter(annee_scolaire_id=annee_id)

    bulletins = []
    for eleve in eleves:
        resultat_annuel = ResultatAnnuel.objects.filter(eleve=eleve, annee_scolaire_id=annee_id).first()
        if resultat_annuel:
            bulletins.append({
                'eleve': eleve,
                'resultat_annuel': resultat_annuel,
                'moyenne': resultat_annuel.moyenne_generale,
                'pourcentage': resultat_annuel.pourcentage_general,
            })
        else:
            bulletins.append({
                'eleve': eleve,
                'resultat_annuel': None,
                'moyenne': 0,
                'pourcentage': 0,
            })

    if user.est_enseignant():
        ecoles = Ecole.objects.filter(id=user.ecole_affectation.id) if user.ecole_affectation else Ecole.objects.none()
        niveaux = Niveau.objects.filter(ecole=user.ecole_affectation, est_reference=False) if user.ecole_affectation else Niveau.objects.none()
        classes = Classe.objects.filter(id=user.classe_affectation.id) if user.classe_affectation else Classe.objects.none()
    elif user.est_agent() or user.est_inspecteur():
        ecoles = Ecole.objects.filter(id=user.ecole_affectation.id) if user.ecole_affectation else Ecole.objects.none()
        niveaux = Niveau.objects.filter(ecole=user.ecole_affectation, est_reference=False) if user.ecole_affectation else Niveau.objects.none()
        classes = Classe.objects.filter(ecole=user.ecole_affectation, est_reference=False) if user.ecole_affectation else Classe.objects.none()
    elif user.est_proved():
        if user.province_affectation:
            ecoles = Ecole.objects.filter(province=user.province_affectation)
            niveaux = Niveau.objects.filter(ecole__in=ecoles, est_reference=False)
            classes = Classe.objects.filter(ecole__in=ecoles, est_reference=False)
        else:
            ecoles = Ecole.objects.none()
            niveaux = Niveau.objects.none()
            classes = Classe.objects.none()
    else:
        ecoles = Ecole.objects.all()
        niveaux = Niveau.objects.filter(est_reference=False)
        classes = Classe.objects.filter(est_reference=False)

    context = {
        'bulletins': bulletins,
        'ecoles': ecoles,
        'niveaux': niveaux,
        'classes': classes,
        'annees': AnneeScolaire.objects.all(),
        'selected_ecole': ecole_id,
        'selected_niveau': niveau_id,
        'selected_classe': classe_id,
        'selected_annee': annee_id,
    }
    return render(request, 'ecoles/bulletin_list.html', context)

# ===================== ÉLÈVES SANS NOTES =====================
@login_required
def eleves_sans_notes(request):
    user = request.user
    cours_id = request.GET.get('cours')
    annee_id = request.GET.get('annee')
    classe_id = request.GET.get('classe')
    evaluation_id = request.GET.get('evaluation')

    if user.est_parent():
        messages.warning(request, "Vous n'avez pas accès à cette page.")
        return redirect('ecoles:dashboard')

    if user.est_enseignant():
        if user.classe_affectation:
            eleves = Eleve.objects.filter(classe=user.classe_affectation)
            classes = Classe.objects.filter(id=user.classe_affectation.id, est_reference=False)
            cours_qs = Cours.objects.filter(classe=user.classe_affectation, est_reference=False)
        else:
            eleves = Eleve.objects.none()
            classes = Classe.objects.none()
            cours_qs = Cours.objects.none()
    elif user.est_agent() or user.est_inspecteur():
        if user.ecole_affectation:
            eleves = Eleve.objects.filter(ecole=user.ecole_affectation)
            classes = Classe.objects.filter(ecole=user.ecole_affectation, est_reference=False)
            cours_qs = Cours.objects.filter(ecole=user.ecole_affectation, est_reference=False)
        else:
            eleves = Eleve.objects.none()
            classes = Classe.objects.none()
            cours_qs = Cours.objects.none()
    elif user.est_proved():
        if user.province_affectation:
            ecoles = Ecole.objects.filter(province=user.province_affectation)
            eleves = Eleve.objects.filter(ecole__in=ecoles)
            classes = Classe.objects.filter(ecole__in=ecoles, est_reference=False)
            cours_qs = Cours.objects.filter(ecole__in=ecoles, est_reference=False)
        else:
            eleves = Eleve.objects.none()
            classes = Classe.objects.none()
            cours_qs = Cours.objects.none()
    else:  # Admin
        eleves = Eleve.objects.all()
        classes = Classe.objects.filter(est_reference=False)
        cours_qs = Cours.objects.filter(est_reference=False)

    if classe_id:
        eleves = eleves.filter(classe_id=classe_id)

    eval_configs = []
    if cours_id:
        try:
            cours = Cours.objects.get(pk=cours_id)
            cycle_eval = CycleEvaluation.objects.filter(cours=cours).first()
            if cycle_eval:
                eval_configs = cycle_eval.evaluations.all().order_by('cycle_num', 'ordre')
        except Cours.DoesNotExist:
            cours = None
            eval_configs = []
    else:
        cours = None

    if cours_id and annee_id:
        try:
            annee = AnneeScolaire.objects.get(pk=annee_id)
        except AnneeScolaire.DoesNotExist:
            messages.error(request, 'Année invalide.')
            return redirect('ecoles:resultat_list')

        if evaluation_id:
            try:
                eval_config = EvaluationConfig.objects.get(pk=evaluation_id)
                if eval_config.cycle_evaluation.cours.id != int(cours_id):
                    messages.error(request, 'Évaluation invalide pour ce cours.')
                    return redirect('ecoles:eleves_sans_notes')
                eleves_avec_notes = EvaluationResultat.objects.filter(
                    cours_id=cours_id,
                    annee_scolaire=annee,
                    evaluation_config=eval_config
                ).values_list('eleve_id', flat=True).distinct()
            except EvaluationConfig.DoesNotExist:
                messages.error(request, 'Évaluation invalide.')
                return redirect('ecoles:eleves_sans_notes')
        else:
            eleves_avec_notes = EvaluationResultat.objects.filter(
                cours_id=cours_id,
                annee_scolaire=annee
            ).values_list('eleve_id', flat=True).distinct()

        eleves_sans = eleves.exclude(id__in=eleves_avec_notes)

        paginator = Paginator(eleves_sans, 20)
        page = request.GET.get('page')
        eleves_sans = paginator.get_page(page)

        context = {
            'eleves': eleves_sans,
            'cours': cours,
            'annee': annee,
            'classe_selected': classe_id,
            'classes': classes,
            'cours_list': cours_qs,
            'annees': AnneeScolaire.objects.all().order_by('-annee'),
            'selected_cours': cours_id,
            'selected_annee': annee_id,
            'selected_evaluation': evaluation_id,
            'eval_configs': eval_configs,
            'has_filter': True,
        }
    else:
        context = {
            'eleves': None,
            'classes': classes,
            'cours_list': cours_qs,
            'annees': AnneeScolaire.objects.all().order_by('-annee'),
            'selected_cours': cours_id,
            'selected_annee': annee_id,
            'selected_evaluation': None,
            'eval_configs': eval_configs,
            'has_filter': False,
        }

    return render(request, 'ecoles/eleves_sans_notes.html', context)

# ===================== CORBEILLE =====================
def trash_list(request):
    items = []
    models = [Ecole, Niveau, Classe, Domaine, Cours, Eleve, Province]
    for model in models:
        if hasattr(model, 'all_objects'):
            qs = model.all_objects.filter(deleted_at__isnull=False)
            for obj in qs:
                items.append({
                    'id': obj.id,
                    'name': str(obj),
                    'model': model.__name__,
                    'deleted_at': obj.deleted_at,
                })
    items.sort(key=lambda x: x['deleted_at'], reverse=True)

    context = {
        'trash_items': items,
        'title': 'Corbeille',
    }
    return render(request, 'ecoles/trash_list.html', context)

def restore_item(request, model_name, pk):
    model_map = {
        'Ecole': Ecole,
        'Niveau': Niveau,
        'Classe': Classe,
        'Domaine': Domaine,
        'Cours': Cours,
        'Eleve': Eleve,
        'Province': Province,
    }
    model = model_map.get(model_name)
    if not model:
        messages.error(request, 'Modèle inconnu.')
        return redirect('ecoles:trash_list')

    obj = get_object_or_404(model.all_objects, pk=pk, deleted_at__isnull=False)
    obj.restore()
    messages.success(request, f"L'objet '{obj}' a été restauré avec succès.")
    return redirect('ecoles:trash_list')

def permanent_delete(request, model_name, pk):
    model_map = {
        'Ecole': Ecole,
        'Niveau': Niveau,
        'Classe': Classe,
        'Domaine': Domaine,
        'Cours': Cours,
        'Eleve': Eleve,
        'Province': Province,
    }
    model = model_map.get(model_name)
    if not model:
        messages.error(request, 'Modèle inconnu.')
        return redirect('ecoles:trash_list')

    obj = get_object_or_404(model.all_objects, pk=pk, deleted_at__isnull=False)
    model.all_objects.filter(pk=pk).delete()

    messages.success(request, f"L'objet '{obj}' a été supprimé définitivement.")
    return redirect('ecoles:trash_list')

@login_required
def empty_trash(request):
    if not request.user.est_administrateur():
        messages.error(request, 'Accès non autorisé.')
        return redirect('ecoles:trash_list')

    models = [Ecole, Niveau, Classe, Domaine, Cours, Eleve, Province]
    deleted_count = 0
    for model in models:
        if hasattr(model, 'all_objects'):
            count = model.all_objects.filter(deleted_at__isnull=False).count()
            model.all_objects.filter(deleted_at__isnull=False).delete()
            deleted_count += count

    messages.success(request, f'La corbeille a été vidée définitivement ({deleted_count} élément(s) supprimé(s)).')
    return redirect('ecoles:trash_list')

# ===================== API =====================
@login_required
def api_get_niveaux(request):
    ecole_id = request.GET.get('ecole_id')
    if not ecole_id:
        return JsonResponse([], safe=False)
    niveaux = Niveau.objects.filter(ecole_id=ecole_id, est_reference=False).values('id', 'nom')
    return JsonResponse(list(niveaux), safe=False)

@login_required
def api_get_classes(request):
    ecole_id = request.GET.get('ecole_id')
    niveau_id = request.GET.get('niveau_id')
    queryset = Classe.objects.filter(est_reference=False)
    if ecole_id:
        queryset = queryset.filter(ecole_id=ecole_id)
    if niveau_id:
        queryset = queryset.filter(niveau_id=niveau_id)
    classes = queryset.values('id', 'nom')
    return JsonResponse(list(classes), safe=False)

@login_required
def api_get_classes_by_niveau(request):
    niveau_id = request.GET.get('niveau_id')
    if not niveau_id:
        return JsonResponse([], safe=False)
    classes = Classe.objects.filter(niveau_id=niveau_id).values('id', 'nom').order_by('nom')
    return JsonResponse(list(classes), safe=False)

@login_required
def api_get_domaines_by_niveau(request):
    niveau_id = request.GET.get('niveau_id')
    if not niveau_id:
        return JsonResponse([], safe=False)
    domaines = Domaine.objects.filter(niveaux__id=niveau_id).values('id', 'nom').order_by('nom')
    return JsonResponse(list(domaines), safe=False)

@login_required
def api_get_eleves(request):
    ecole_id = request.GET.get('ecole_id')
    niveau_id = request.GET.get('niveau_id')
    classe_id = request.GET.get('classe_id')
    queryset = Eleve.objects.all()
    if ecole_id:
        queryset = queryset.filter(ecole_id=ecole_id)
    if niveau_id:
        queryset = queryset.filter(niveau_id=niveau_id)
    if classe_id:
        queryset = queryset.filter(classe_id=classe_id)
    eleves = queryset.values('id', 'nom', 'postnom', 'prenom')
    for e in eleves:
        e['nom_complet'] = f"{e['nom']} {e['postnom']} {e['prenom']}".strip()
    return JsonResponse(list(eleves), safe=False)

@login_required
def api_get_cours(request):
    niveau_id = request.GET.get('niveau_id')
    classe_id = request.GET.get('classe_id')
    queryset = Cours.objects.filter(est_reference=False)
    if niveau_id:
        queryset = queryset.filter(niveau_id=niveau_id)
    if classe_id:
        queryset = queryset.filter(classe_id=classe_id)
    cours = queryset.values('id', 'nom')
    return JsonResponse(list(cours), safe=False)

# ===================== API PUBLIQUES =====================
def autocomplete_eleves(request):
    q = request.GET.get('q', '').strip()
    if len(q) < 2:
        return JsonResponse({'results': []})

    eleves = Eleve.objects.filter(
        Q(nom__icontains=q) |
        Q(postnom__icontains=q) |
        Q(prenom__icontains=q)
    )[:10]

    results = []
    for eleve in eleves:
        results.append({
            'nom_complet': eleve.get_nom_complet(),
            'classe': eleve.classe.nom if eleve.classe else '-',
            'ecole': eleve.ecole.nom if eleve.ecole else '-',
            'matricule': eleve.matricule or '-'
        })
    return JsonResponse({'results': results})

def recherche_resultats(request):
    nom_complet = request.GET.get('nom_complet', '').strip()
    if not nom_complet:
        return JsonResponse({'success': False, 'error': 'Nom complet requis'})

    parts = nom_complet.split()
    q_objects = Q()
    for part in parts:
        q_objects |= Q(nom__icontains=part) | Q(postnom__icontains=part) | Q(prenom__icontains=part)

    eleves = Eleve.objects.filter(q_objects).distinct()
    if not eleves.exists():
        return JsonResponse({'success': False, 'error': 'Élève non trouvé'})

    eleve = eleves.first()
    annee = AnneeScolaire.objects.filter(est_actuelle=True).first()
    if not annee:
        annee = AnneeScolaire.objects.order_by('-annee').first()
    if not annee:
        return JsonResponse({'success': False, 'error': 'Aucune année scolaire trouvée'})

    resultats_par_cours = {}
    cours_list = eleve.classe.cours.all() if eleve.classe else []

    for cours in cours_list:
        cycle_eval, created = CycleEvaluation.objects.get_or_create(cours=cours)
        if created:
            cycle_eval.creer_evaluations_par_defaut()

        eval_configs = cycle_eval.evaluations.all().order_by('cycle_num', 'ordre')
        evaluations = []
        for config in eval_configs:
            try:
                resultat = EvaluationResultat.objects.get(
                    eleve=eleve,
                    cours=cours,
                    annee_scolaire=annee,
                    evaluation_config=config
                )
                evaluations.append({
                    'cycle': config.cycle_num,
                    'periode': config.periode_num,
                    'type': config.type,
                    'points_obtenus': float(resultat.points_obtenus),
                    'points_max': config.points_max
                })
            except EvaluationResultat.DoesNotExist:
                pass

        if evaluations:
            resultats_par_cours[cours.id] = {
                'cours_nom': cours.nom,
                'evaluations': evaluations
            }

    resultat_annuel = ResultatAnnuel.objects.filter(eleve=eleve, annee_scolaire=annee).first()
    annuel_data = {
        'pourcentage_general': float(resultat_annuel.pourcentage_general) if resultat_annuel else None
    }

    response_data = {
        'success': True,
        'eleve': {
            'nom_complet': eleve.get_nom_complet(),
            'matricule': eleve.matricule,
            'classe': eleve.classe.nom if eleve.classe else '-',
            'ecole': eleve.ecole.nom if eleve.ecole else '-',
            'prenom': eleve.prenom,
            'nom': eleve.nom
        },
        'resultats_par_cours': resultats_par_cours,
        'resultat_annuel': annuel_data
    }
    return JsonResponse(response_data)