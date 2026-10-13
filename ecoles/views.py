# ============================================================================
# ecoles/views.py
# ============================================================================

import logging
import requests
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q, Sum, Count, Avg, F, Min
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.http import JsonResponse
from django.utils import timezone
from .models import (
    Ecole, Niveau, Classe, Cours, AnneeScolaire,
    CycleEvaluation, EvaluationConfig, EvaluationResultat,
    ResultatCycle, ResultatAnnuel, Province,
    Section
)
from .forms import (
    EcoleForm, NiveauForm, ClasseForm, CoursForm,
    CycleEvaluationConfigForm,
    AnneeScolaireForm, CycleEvaluationForm, EvaluationConfigFormSet,
    ResultatSelectionForm, EvaluationResultatForm, ProvinceForm,
    ClasseDuplicateForm,
    SectionForm
)
from eleves.models import Eleve
from .utils import (
    recalculer_resultats_eleve,
    synchroniser_classe_ref_vers_instances,
    synchroniser_cours_ref_vers_instances,
)
from accounts.models import AuditLog
from actualites.models import Article


logger = logging.getLogger(__name__)


# ===================== CONSTANTES =====================

NOM_NIVEAU_PAR_DEFAUT = "MAXIMA"
NOM_SECTION_PAR_DEFAUT = "MAXIMA"


# ===================== FONCTIONS UTILITAIRES =====================

def get_annee_actuelle():
    annee = AnneeScolaire.objects.filter(est_actuelle=True).first()
    if not annee:
        annee = AnneeScolaire.objects.order_by('-annee').first()
    return annee


def calculer_taux_reussite(queryset_resultats, seuil=10):
    total = queryset_resultats.count()
    if total == 0:
        return 0
    reussis = queryset_resultats.filter(moyenne_generale__gte=seuil).count()
    return round((reussis / total) * 100, 1)


def calculer_moyenne_generale(queryset_resultats):
    avg = queryset_resultats.aggregate(avg=Avg('moyenne_generale'))['avg']
    return round(avg, 2) if avg is not None else 0


def _nom_niveau_ou_defaut(niveau):
    if niveau and niveau.nom and niveau.nom.strip():
        return niveau.nom.strip()
    return NOM_NIVEAU_PAR_DEFAUT


def _nom_section_ou_defaut(section):
    if section and section.nom and section.nom.strip():
        return section.nom.strip()
    return NOM_SECTION_PAR_DEFAUT


def _label_classe_complet(classe):
    nom = classe.nom or "Sans nom"
    niveau_nom = NOM_NIVEAU_PAR_DEFAUT
    section_nom = ''

    if classe.niveau:
        niveau_nom = _nom_niveau_ou_defaut(classe.niveau)
        if classe.niveau.section:
            section_nom = _nom_section_ou_defaut(classe.niveau.section)

    if section_nom:
        return f"{nom} ({niveau_nom} - {section_nom})"
    return f"{nom} ({niveau_nom})"


def _stocker_rapport_sync(request, rapport, action_label=""):
    defaults = {
        'instances_traitees': 0,
        'cours_ajoutes': 0,
        'cours_modifies': 0,
        'classes_ajoutees': 0,
        'classes_modifiees': 0,
        'evaluations_ajoutees': 0,
        'evaluations_modifiees': 0,
        'evaluations_supprimees': 0,
        'evaluations_bloquees': 0,
        'doublons_nettoyes': 0,
        'details_ecoles': [],
        'erreurs': [],
    }
    for k, v in defaults.items():
        rapport.setdefault(k, v)

    nb_instances = rapport.get('instances_traitees', 0)
    nb_cours_ajoutes = rapport.get('cours_ajoutes', 0)
    nb_cours_modifies = rapport.get('cours_modifies', 0)
    nb_classes_ajoutees = rapport.get('classes_ajoutees', 0)
    nb_classes_modifiees = rapport.get('classes_modifiees', 0)
    nb_evals = (
        rapport.get('evaluations_ajoutees', 0) +
        rapport.get('evaluations_modifiees', 0) +
        rapport.get('evaluations_supprimees', 0)
    )
    nb_bloques = rapport.get('evaluations_bloquees', 0)
    nb_doublons = rapport.get('doublons_nettoyes', 0)

    rapport['date_sync'] = timezone.now().strftime('%d/%m/%Y à %H:%M')
    rapport['utilisateur'] = request.user.get_full_name() or request.user.username
    rapport['force_delete_used'] = False
    rapport['action_source'] = action_label
    rapport['niveau_ref'] = rapport.get('niveau_ref') or rapport.get('classe_ref', '-')

    rapport['total_operations'] = (
        nb_cours_ajoutes + nb_cours_modifies +
        nb_classes_ajoutees + nb_classes_modifiees +
        rapport.get('evaluations_ajoutees', 0) +
        rapport.get('evaluations_modifiees', 0) +
        rapport.get('evaluations_supprimees', 0)
    )

    rapport['nb_ecoles_affectees'] = sum(
        1 for d in rapport.get('details_ecoles', [])
        if (d.get('classes_ajoutees', 0) + d.get('classes_modifiees', 0) +
            d.get('cours_ajoutes', 0) + d.get('cours_modifies', 0) +
            d.get('evaluations_ajoutees', 0) + d.get('evaluations_modifiees', 0) +
            d.get('evaluations_supprimees', 0)) > 0
    )

    if nb_instances > 0:
        details = []
        if nb_cours_ajoutes: details.append(f"{nb_cours_ajoutes} cours ajouté(s)")
        if nb_cours_modifies: details.append(f"{nb_cours_modifies} cours modifié(s)")
        if nb_classes_ajoutees: details.append(f"{nb_classes_ajoutees} classe(s) ajoutée(s)")
        if nb_classes_modifiees: details.append(f"{nb_classes_modifiees} classe(s) modifiée(s)")
        if nb_evals: details.append(f"{nb_evals} évaluation(s)")
        details_str = ", ".join(details) if details else "aucune modification"
        messages.info(
            request,
            f"🔄 Synchronisation automatique appliquée à "
            f"{nb_instances} école(s) ({action_label}) : {details_str}."
        )
    else:
        messages.info(request, f"ℹ️ Aucune école à synchroniser pour cette référence.")

    if nb_bloques > 0:
        messages.warning(
            request,
            f"⚠️ {nb_bloques} conflit(s) détecté(s) lors de la synchronisation."
        )
    if nb_doublons > 0:
        messages.info(request, f"🧹 {nb_doublons} doublon(s) nettoyé(s).")

    request.session['sync_rapport'] = rapport


def get_geo_data_from_ips(ips):
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
        except Exception:
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
    now = timezone.now()
    cache_data = None
    cache_time_key = f"{cache_key}_time"

    if cache_key in request.session and cache_time_key in request.session:
        try:
            cache_time_str = request.session[cache_time_key]
            cache_time = datetime.fromisoformat(cache_time_str)
            cache_time = timezone.make_aware(cache_time)
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
                'country_items': [], 'city_items': [],
                'total_pays': 0, 'total_villes': 0,
                'country_labels': [], 'country_data': [],
            }
        request.session[cache_key] = cache_data
        request.session[cache_time_key] = now.isoformat()

    return cache_data


# ===================== PAGE D'ACCUEIL PUBLIQUE =====================
def index_view(request):
    articles = Article.objects.filter(
        statut=Article.Statut.PUBLIE,
        est_visible=True
    ).order_by('-date_publication')[:3]
    return render(request, 'ecoles/index.html', {'articles': articles})


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

    if user.est_administrateur():
        province_id = request.GET.get('province')
        province_filter = None
        if province_id:
            try:
                province_filter = Province.objects.get(pk=province_id)
            except Province.DoesNotExist:
                province_filter = None

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

        total_ecoles = ecoles_qs.count()
        total_niveaux = niveaux_qs.count()
        total_classes = classes_qs.count()
        total_cours = cours_qs.count()
        total_eleves = eleves_qs.count()
        total_notes = resultats_qs.filter(annee_scolaire=annee_actuelle).count() if annee_actuelle else 0

        if annee_actuelle:
            resultats_annuels_qs = resultats_annuels_qs.filter(annee_scolaire=annee_actuelle)
        moyenne_generale_globale = calculer_moyenne_generale(resultats_annuels_qs)
        taux_reussite_global = calculer_taux_reussite(resultats_annuels_qs)

        eleves_par_ecole = eleves_qs.values('ecole__nom').annotate(total=Count('id')).order_by('ecole__nom')
        ecole_labels = [item['ecole__nom'] for item in eleves_par_ecole]
        ecole_counts = [item['total'] for item in eleves_par_ecole]

        eleves_par_sexe = eleves_qs.values('sexe').annotate(total=Count('id'))
        sexe_map = dict(Eleve.SEXE_CHOICES)
        sexe_labels = [sexe_map.get(item['sexe'], item['sexe']) for item in eleves_par_sexe]
        sexe_counts = [item['total'] for item in eleves_par_sexe]

        eleves_par_niveau = eleves_qs.values('niveau__nom').annotate(total=Count('id')).order_by('niveau__nom')
        niveau_labels = [
            _nom_niveau_ou_defaut({'nom': item['niveau__nom']}) if not item['niveau__nom'] else item['niveau__nom']
            for item in eleves_par_niveau
        ]
        niveau_counts = [item['total'] for item in eleves_par_niveau]

        stats_par_ecole = []
        for ecole in ecoles_qs:
            res = resultats_annuels_qs.filter(eleve__ecole=ecole)
            if res.exists():
                total = res.count()
                reussis = res.filter(moyenne_generale__gte=10).count()
                taux = (reussis / total * 100) if total > 0 else 0
                stats_par_ecole.append({
                    'nom': ecole.nom, 'total': total,
                    'reussis': reussis, 'taux': round(taux, 1)
                })
            else:
                nb_eleves = eleves_qs.filter(ecole=ecole).count()
                stats_par_ecole.append({'nom': ecole.nom, 'total': nb_eleves, 'reussis': 0, 'taux': 0})
        stats_par_ecole = sorted(stats_par_ecole, key=lambda x: x['taux'], reverse=True)

        provinces = Province.objects.all().order_by('nom')

        seven_days_ago = timezone.now() - timedelta(days=7)
        view_ips = AuditLog.objects.filter(
            action=AuditLog.ActionType.VIEW, success=True, timestamp__gte=seven_days_ago
        ).values_list('ip_address', flat=True).distinct()[:100]
        visitor_data = get_cached_geo_data(request, 'visitor_geo_cache', lambda: view_ips, ttl_minutes=10)

        login_ips = AuditLog.objects.filter(
            action=AuditLog.ActionType.LOGIN, success=True
        ).values_list('ip_address', flat=True).distinct()[:100]
        user_data = get_cached_geo_data(request, 'user_geo_cache', lambda: login_ips, ttl_minutes=10)

        context.update({
            'role': 'admin',
            'total_ecoles': total_ecoles, 'total_niveaux': total_niveaux,
            'total_classes': total_classes, 'total_cours': total_cours,
            'total_eleves': total_eleves, 'total_notes': total_notes,
            'moyenne_generale_globale': moyenne_generale_globale,
            'taux_reussite_global': taux_reussite_global,
            'ecole_labels': ecole_labels, 'ecole_counts': ecole_counts,
            'sexe_labels': sexe_labels, 'sexe_counts': sexe_counts,
            'niveau_labels': niveau_labels, 'niveau_counts': niveau_counts,
            'stats_par_ecole': stats_par_ecole,
            'provinces': provinces, 'province_filter': province_filter,
            'visitor_country_items': visitor_data['country_items'],
            'visitor_city_items': visitor_data['city_items'],
            'visitor_country_labels': visitor_data['country_labels'],
            'visitor_country_data': visitor_data['country_data'],
            'total_visitor_pays': visitor_data['total_pays'],
            'total_visitor_villes': visitor_data['total_villes'],
            'user_country_items': user_data['country_items'],
            'user_city_items': user_data['city_items'],
            'user_country_labels': user_data['country_labels'],
            'user_country_data': user_data['country_data'],
            'total_user_pays': user_data['total_pays'],
            'total_user_villes': user_data['total_villes'],
        })
        template = 'ecoles/dashboard_admin.html'

    elif user.est_ministre():
        provinces = Province.objects.all().order_by('nom')
        total_provinces = provinces.count()
        total_ecoles = Ecole.objects.count()
        total_eleves = Eleve.objects.count()
        total_niveaux = Niveau.objects.filter(est_reference=False).count()
        total_classes = Classe.objects.filter(est_reference=False).count()
        total_cours = Cours.objects.filter(est_reference=False).count()
        total_notes = EvaluationResultat.objects.filter(annee_scolaire=annee_actuelle).count() if annee_actuelle else 0

        resultats_annuels_qs = ResultatAnnuel.objects.all()
        if annee_actuelle:
            resultats_annuels_qs = resultats_annuels_qs.filter(annee_scolaire=annee_actuelle)

        moyenne_generale_nationale = calculer_moyenne_generale(resultats_annuels_qs)
        taux_reussite_national = calculer_taux_reussite(resultats_annuels_qs)

        stats_par_province = []
        for province in provinces:
            ecoles_prov = Ecole.objects.filter(province=province)
            eleves_prov = Eleve.objects.filter(ecole__in=ecoles_prov)
            res_prov = resultats_annuels_qs.filter(eleve__ecole__in=ecoles_prov)
            total_eleves_prov = eleves_prov.count()
            total_ecoles_prov = ecoles_prov.count()

            if res_prov.exists():
                total = res_prov.count()
                reussis = res_prov.filter(moyenne_generale__gte=10).count()
                taux = (reussis / total * 100) if total > 0 else 0
                moyenne_prov = res_prov.aggregate(avg=Avg('moyenne_generale'))['avg'] or 0
                stats_par_province.append({
                    'province': province.nom, 'province_id': province.id,
                    'total_ecoles': total_ecoles_prov, 'total_eleves': total_eleves_prov,
                    'total_resultats': total, 'reussis': reussis,
                    'taux': round(taux, 1), 'moyenne': round(float(moyenne_prov), 2),
                })
            else:
                stats_par_province.append({
                    'province': province.nom, 'province_id': province.id,
                    'total_ecoles': total_ecoles_prov, 'total_eleves': total_eleves_prov,
                    'total_resultats': 0, 'reussis': 0, 'taux': 0, 'moyenne': 0,
                })

        stats_par_province = sorted(stats_par_province, key=lambda x: x['taux'], reverse=True)
        province_labels = [s['province'] for s in stats_par_province]
        province_eleves_data = [s['total_eleves'] for s in stats_par_province]
        province_taux_data = [s['taux'] for s in stats_par_province]
        province_moyennes_data = [s['moyenne'] for s in stats_par_province]

        stats_par_ecole = []
        for ecole in Ecole.objects.all():
            res = resultats_annuels_qs.filter(eleve__ecole=ecole)
            if res.exists():
                total = res.count()
                reussis = res.filter(moyenne_generale__gte=10).count()
                taux = (reussis / total * 100) if total > 0 else 0
                stats_par_ecole.append({
                    'nom': ecole.nom,
                    'province': ecole.province.nom if ecole.province else '-',
                    'total': total, 'reussis': reussis, 'taux': round(taux, 1)
                })
        stats_par_ecole = sorted(stats_par_ecole, key=lambda x: x['taux'], reverse=True)[:10]

        context.update({
            'role': 'ministre',
            'total_provinces': total_provinces, 'total_ecoles': total_ecoles,
            'total_eleves': total_eleves, 'total_niveaux': total_niveaux,
            'total_classes': total_classes, 'total_cours': total_cours,
            'total_notes': total_notes,
            'moyenne_generale_nationale': moyenne_generale_nationale,
            'taux_reussite_national': taux_reussite_national,
            'stats_par_province': stats_par_province,
            'stats_par_ecole': stats_par_ecole,
            'province_labels': province_labels,
            'province_eleves_data': province_eleves_data,
            'province_taux_data': province_taux_data,
            'province_moyennes_data': province_moyennes_data,
        })
        template = 'ecoles/dashboard_ministre.html'

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
                    'nom': ecole.nom, 'total': total,
                    'reussis': reussis, 'taux': round(taux, 1)
                })
        stats_par_ecole = sorted(stats_par_ecole, key=lambda x: x['taux'], reverse=True)

        context.update({
            'role': 'proved',
            'province_nom': province.nom,
            'total_ecoles': total_ecoles, 'total_niveaux': total_niveaux,
            'total_classes': total_classes, 'total_cours': total_cours,
            'total_eleves': total_eleves, 'total_notes': total_notes,
            'moyenne_province': moyenne_province,
            'taux_reussite_province': taux_reussite_province,
            'stats_par_ecole': stats_par_ecole,
        })
        template = 'ecoles/dashboard_proved.html'

    elif user.est_agent():
        total_sections = Section.objects.count()
        total_niveaux_ref = Niveau.objects.filter(est_reference=True, ecole__isnull=True).count()
        total_classes_ref = Classe.objects.filter(est_reference=True, ecole__isnull=True).count()
        total_cours_ref = Cours.objects.filter(est_reference=True, ecole__isnull=True).count()

        total_ecoles = Ecole.objects.count()
        total_provinces = Province.objects.count()
        total_niveaux_inst = Niveau.objects.filter(est_reference=False).count()
        total_classes_inst = Classe.objects.filter(est_reference=False).count()
        total_cours_inst = Cours.objects.filter(est_reference=False).count()

        context.update({
            'role': 'agent',
            'is_agent_global': True,
            'ecole_nom': user.ecole_affectation.nom if user.ecole_affectation else "Système (global)",
            'total_sections': total_sections,
            'total_niveaux_ref': total_niveaux_ref,
            'total_classes_ref': total_classes_ref,
            'total_cours_ref': total_cours_ref,
            'total_ecoles': total_ecoles,
            'total_provinces': total_provinces,
            'total_niveaux_inst': total_niveaux_inst,
            'total_classes_inst': total_classes_inst,
            'total_cours_inst': total_cours_inst,
        })
        template = 'ecoles/dashboard_agent.html'

    elif user.est_inspecteur():
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
                    'nom': cls.nom, 'total': total,
                    'reussis': reussis, 'taux': round(taux, 1)
                })
        stats_par_classe = sorted(stats_par_classe, key=lambda x: x['taux'], reverse=True)

        context.update({
            'role': 'inspecteur',
            'ecole_nom': ecole.nom,
            'total_niveaux': total_niveaux, 'total_classes': total_classes,
            'total_cours': total_cours, 'total_eleves': total_eleves,
            'total_notes': total_notes,
            'moyenne_ecole': moyenne_ecole,
            'taux_reussite_ecole': taux_reussite_ecole,
            'stats_par_classe': stats_par_classe,
        })
        template = 'ecoles/dashboard_agent.html'

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
            'total_eleves': total_eleves, 'total_cours': total_cours,
            'total_notes': total_notes,
            'moyenne_classe': moyenne_classe,
            'taux_reussite_classe': taux_reussite_classe,
            'eleves_moyennes': eleves_moyennes,
        })
        template = 'ecoles/dashboard_enseignant.html'

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
            if not resultat_annuel:
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
    if user.est_parent() or user.est_ministre() or user.est_agent():
        messages.warning(request, "Vous n'avez pas accès à cette liste.")
        return redirect('ecoles:dashboard')

    if user.est_enseignant() or user.est_inspecteur():
        ecoles = Ecole.objects.filter(id=user.ecole_affectation.id) if user.ecole_affectation else Ecole.objects.none()
    elif user.est_proved():
        if user.province_affectation:
            ecoles = Ecole.objects.filter(province=user.province_affectation)
        else:
            ecoles = Ecole.objects.none()
    else:
        ecoles = Ecole.objects.all()

    search = request.GET.get('search', '').strip()
    province_id = request.GET.get('province')
    type_gestion = request.GET.get('type_gestion')
    est_active = request.GET.get('est_active')

    if search:
        ecoles = ecoles.filter(Q(nom__icontains=search) | Q(code__icontains=search))
    if province_id:
        ecoles = ecoles.filter(province_id=province_id)
    if type_gestion:
        ecoles = ecoles.filter(type_gestion=type_gestion)
    if est_active in ['0', '1']:
        ecoles = ecoles.filter(est_active=(est_active == '1'))

    paginator = Paginator(ecoles, 20)
    page = request.GET.get('page')
    ecoles = paginator.get_page(page)

    if user.est_administrateur():
        provinces = Province.objects.all()
    elif user.est_proved():
        provinces = Province.objects.filter(id=user.province_affectation.id) if user.province_affectation else Province.objects.none()
    else:
        if user.ecole_affectation:
            provinces = Province.objects.filter(id=user.ecole_affectation.province.id)
        else:
            provinces = Province.objects.none()

    query_params = ''
    if search:
        query_params += f'&search={search}'
    if province_id:
        query_params += f'&province={province_id}'
    if type_gestion:
        query_params += f'&type_gestion={type_gestion}'
    if est_active in ['0', '1']:
        query_params += f'&est_active={est_active}'

    context = {
        'ecoles': ecoles,
        'provinces': provinces,
        'selected_province': province_id,
        'selected_type_gestion': type_gestion,
        'selected_est_active': est_active,
        'query_params': query_params,
    }
    return render(request, 'ecoles/ecole_list.html', context)


# ===================== DÉTAIL ÉCOLE =====================
@login_required
def ecole_detail(request, pk):
    user = request.user

    if not (user.est_administrateur() or user.est_ministre()
            or user.est_proved() or user.est_inspecteur()):
        messages.error(request, "Vous n'avez pas accès à cette page.")
        return redirect('ecoles:ecole_list')

    ecole = get_object_or_404(Ecole, pk=pk)

    if user.est_proved():
        if not user.province_affectation or ecole.province != user.province_affectation:
            messages.error(request, 'Accès non autorisé à cette école.')
            return redirect('ecoles:ecole_list')
    elif user.est_inspecteur():
        if not user.ecole_affectation or ecole.id != user.ecole_affectation.id:
            messages.error(request, 'Accès non autorisé à cette école.')
            return redirect('ecoles:ecole_list')

    annee_actuelle = get_annee_actuelle()

    total_niveaux = Niveau.objects.filter(ecole=ecole, est_reference=False).count()
    total_classes = Classe.objects.filter(ecole=ecole, est_reference=False).count()
    total_cours = Cours.objects.filter(ecole=ecole, est_reference=False).count()

    sections_ids = Niveau.objects.filter(
        ecole=ecole, est_reference=False, section__isnull=False
    ).values_list('section_id', flat=True).distinct()
    total_sections = Section.objects.filter(id__in=sections_ids).count()

    if total_sections == 0:
        total_sections = Section.objects.count()

    sections_list = Section.objects.filter(
        id__in=sections_ids
    ).order_by('ordre', 'nom')

    total_eleves = Eleve.objects.filter(ecole=ecole).count()

    eleves_par_sexe = Eleve.objects.filter(ecole=ecole).values('sexe').annotate(
        total=Count('id')
    )
    sexe_map = dict(Eleve.SEXE_CHOICES)
    sexe_stats = [
        {'label': sexe_map.get(item['sexe'], item['sexe']), 'count': item['total']}
        for item in eleves_par_sexe
    ]

    eleves_par_niveau = Eleve.objects.filter(ecole=ecole).values(
        'niveau__nom'
    ).annotate(total=Count('id')).order_by('-total')
    niveau_stats = [
        {
            'label': item['niveau__nom'] if item['niveau__nom'] and item['niveau__nom'].strip() else NOM_NIVEAU_PAR_DEFAUT,
            'count': item['total']
        }
        for item in eleves_par_niveau
    ]

    resultats_annuels = ResultatAnnuel.objects.filter(
        eleve__ecole=ecole,
        annee_scolaire=annee_actuelle
    ) if annee_actuelle else ResultatAnnuel.objects.none()

    moyenne_generale = calculer_moyenne_generale(resultats_annuels)
    taux_reussite = calculer_taux_reussite(resultats_annuels)
    total_resultats = resultats_annuels.count()

    stats_par_classe = []
    for cls in Classe.objects.filter(ecole=ecole, est_reference=False):
        res = resultats_annuels.filter(eleve__classe=cls)
        if res.exists():
            total = res.count()
            reussis = res.filter(moyenne_generale__gte=10).count()
            taux = (reussis / total * 100) if total > 0 else 0
            moyenne_cls = res.aggregate(avg=Avg('moyenne_generale'))['avg'] or 0
            stats_par_classe.append({
                'id': cls.id,
                'nom': cls.nom,
                'niveau': _nom_niveau_ou_defaut(cls.niveau),
                'total': total,
                'reussis': reussis,
                'taux': round(taux, 1),
                'moyenne': round(float(moyenne_cls), 2),
            })
        else:
            nb_eleves = Eleve.objects.filter(classe=cls).count()
            stats_par_classe.append({
                'id': cls.id,
                'nom': cls.nom,
                'niveau': _nom_niveau_ou_defaut(cls.niveau),
                'total': nb_eleves,
                'reussis': 0,
                'taux': 0,
                'moyenne': 0,
            })
    stats_par_classe = sorted(stats_par_classe, key=lambda x: x['taux'], reverse=True)

    niveaux_list = []
    for niveau in Niveau.objects.filter(ecole=ecole, est_reference=False).order_by('nom'):
        nb_eleves = Eleve.objects.filter(niveau=niveau, ecole=ecole).count()
        nb_classes = Classe.objects.filter(niveau=niveau, ecole=ecole).count()
        nb_cours = Cours.objects.filter(niveau=niveau, ecole=ecole).count()
        niveaux_list.append({
            'id': niveau.id,
            'nom': _nom_niveau_ou_defaut(niveau),
            'section': _nom_section_ou_defaut(niveau.section),
            'nb_eleves': nb_eleves,
            'nb_classes': nb_classes,
            'nb_cours': nb_cours,
        })

    sexe_par_niveau = []
    for niveau_data in niveaux_list:
        niveau_obj = Niveau.objects.filter(pk=niveau_data['id']).first()
        if niveau_obj:
            eleves_niveau = Eleve.objects.filter(niveau=niveau_obj, ecole=ecole)
            masculin = eleves_niveau.filter(sexe='M').count()
            feminin = eleves_niveau.filter(sexe='F').count()
            sexe_par_niveau.append({
                'niveau': niveau_data['nom'],
                'masculin': masculin,
                'feminin': feminin,
                'total': niveau_data['nb_eleves'],
            })

    context = {
        'ecole': ecole,
        'annee_actuelle': annee_actuelle,
        'total_niveaux': total_niveaux,
        'total_classes': total_classes,
        'total_cours': total_cours,
        'total_sections': total_sections,
        'sections_list': sections_list,
        'total_eleves': total_eleves,
        'sexe_stats': sexe_stats,
        'niveau_stats': niveau_stats,
        'sexe_par_niveau': sexe_par_niveau,
        'moyenne_generale': moyenne_generale,
        'taux_reussite': taux_reussite,
        'total_resultats': total_resultats,
        'stats_par_classe': stats_par_classe,
        'niveaux_list': niveaux_list,
        'user_can_edit': user.est_administrateur() or user.est_proved(),
    }
    return render(request, 'ecoles/ecole_detail.html', context)


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
                        existing = Niveau.all_objects.filter(
                            nom=niveau_ref.nom, ecole=ecole,
                            section=niveau_ref.section, est_reference=False
                        ).first()
                        if existing:
                            if existing.deleted_at:
                                existing.deleted_at = None
                                existing.section = niveau_ref.section
                                existing.reference_source = niveau_ref
                                existing.save()
                                messages.success(request, f'Niveau {niveau_ref.nom} restauré avec succès.')
                            else:
                                messages.warning(request, f"Le niveau {niveau_ref.nom} existe déjà.")
                        else:
                            niveau_ref.affecter_a_ecole(ecole)
                            messages.success(request, f'Niveau {niveau_ref.nom} attribué avec succès.')
                    except Exception as e:
                        messages.warning(request, f'Erreur pour {niveau_ref.nom}: {str(e)}')
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
                    existing = Niveau.all_objects.filter(
                        nom=niveau_ref.nom, ecole=ecole,
                        section=niveau_ref.section, est_reference=False
                    ).first()
                    if existing:
                        if existing.deleted_at:
                            existing.deleted_at = None
                            existing.section = niveau_ref.section
                            existing.reference_source = niveau_ref
                            existing.save()
                            messages.success(request, f'Niveau {niveau_ref.nom} restauré avec succès.')
                        else:
                            messages.warning(request, f"Le niveau {niveau_ref.nom} existe déjà.")
                    else:
                        try:
                            niveau_ref.affecter_a_ecole(ecole)
                            messages.success(request, f'Niveau {niveau_ref.nom} attribué avec succès.')
                        except Exception as e:
                            messages.warning(request, f'Erreur pour {niveau_ref.nom}: {str(e)}')
            messages.success(request, 'École modifiée avec succès.')
            return redirect('ecoles:ecole_list')
    else:
        form = EcoleForm(instance=ecole, user=request.user)
        niveaux_attribues = Niveau.all_objects.filter(ecole=ecole, est_reference=False)
        return render(request, 'ecoles/ecole_form.html', {
            'form': form, 'title': 'Modifier une école',
            'niveaux_attribues': niveaux_attribues
        })
    return render(request, 'ecoles/ecole_form.html', {'form': form, 'title': 'Modifier une école'})


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
    if user.est_parent() or user.est_ministre():
        messages.warning(request, "Vous n'avez pas accès à cette liste.")
        return redirect('ecoles:dashboard')

    section_id = request.GET.get('section')

    if user.est_enseignant():
        niveaux = Niveau.objects.filter(ecole=user.ecole_affectation, est_reference=False) if user.ecole_affectation else Niveau.objects.none()
    elif user.est_agent():
        niveaux = Niveau.objects.all().order_by('-est_reference', 'nom')
    elif user.est_inspecteur():
        if user.ecole_affectation:
            niveaux = Niveau.objects.filter(
                Q(est_reference=True) | Q(ecole=user.ecole_affectation, est_reference=False)
            )
        else:
            niveaux = Niveau.objects.filter(est_reference=True)
    elif user.est_proved():
        if user.province_affectation:
            ecoles = Ecole.objects.filter(province=user.province_affectation)
            niveaux = Niveau.objects.filter(
                Q(est_reference=True) | Q(ecole__in=ecoles, est_reference=False)
            )
        else:
            niveaux = Niveau.objects.filter(est_reference=True)
    else:
        niveaux = Niveau.objects.all().order_by('-est_reference', 'nom')

    if section_id:
        niveaux = niveaux.filter(section_id=section_id)

    paginator = Paginator(niveaux, 20)
    page = request.GET.get('page')
    niveaux = paginator.get_page(page)

    sections = Section.objects.all()
    context = {
        'niveaux': niveaux, 'sections': sections,
        'selected_section': section_id,
    }
    return render(request, 'ecoles/niveau_list.html', context)


@login_required
def niveau_create(request):
    if not (request.user.est_administrateur() or request.user.est_agent()):
        messages.error(request, 'Seuls les administrateurs et agents peuvent créer des niveaux de référence.')
        return redirect('ecoles:dashboard')
    if request.method == 'POST':
        form = NiveauForm(request.POST, user=request.user, is_reference=True)
        form.instance.est_reference = True
        if form.is_valid():
            niveau = form.save(commit=False)
            niveau.ecole = None
            if not niveau.nom or not niveau.nom.strip():
                niveau.nom = NOM_NIVEAU_PAR_DEFAUT
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
    if user.est_parent() or user.est_ministre():
        messages.error(request, 'Accès non autorisé.')
        return redirect('ecoles:dashboard')

    if niveau.est_reference:
        if not (user.est_administrateur() or user.est_agent()):
            messages.error(request, 'Accès non autorisé.')
            return redirect('ecoles:dashboard')
        is_reference = True
    else:
        if user.est_agent():
            pass
        elif user.est_inspecteur() and niveau.ecole != user.ecole_affectation:
            messages.error(request, 'Accès non autorisé.')
            return redirect('ecoles:dashboard')
        elif user.est_proved() and (niveau.ecole and niveau.ecole.province != user.province_affectation):
            messages.error(request, 'Accès non autorisé.')
            return redirect('ecoles:dashboard')
        is_reference = False

    if request.method == 'POST':
        form = NiveauForm(request.POST, instance=niveau, user=user, is_reference=is_reference)
        if form.is_valid():
            niveau = form.save(commit=False)
            if not niveau.nom or not niveau.nom.strip():
                niveau.nom = NOM_NIVEAU_PAR_DEFAUT
            niveau.save()
            messages.success(request, 'Niveau modifié avec succès.')
            return redirect('ecoles:niveau_list')
    else:
        form = NiveauForm(instance=niveau, user=user, is_reference=is_reference)
    return render(request, 'ecoles/niveau_form.html', {'form': form, 'title': 'Modifier un niveau'})


@login_required
def niveau_delete(request, pk):
    niveau = get_object_or_404(Niveau, pk=pk)
    user = request.user
    if user.est_parent() or user.est_ministre():
        messages.error(request, 'Accès non autorisé.')
        return redirect('ecoles:dashboard')

    if niveau.est_reference:
        if not (user.est_administrateur() or user.est_agent()):
            messages.error(request, 'Accès non autorisé.')
            return redirect('ecoles:dashboard')
    else:
        if user.est_agent():
            pass
        elif user.est_inspecteur() and niveau.ecole != user.ecole_affectation:
            messages.error(request, 'Accès non autorisé.')
            return redirect('ecoles:dashboard')
        elif user.est_proved() and (niveau.ecole and niveau.ecole.province != user.province_affectation):
            messages.error(request, 'Accès non autorisé.')
            return redirect('ecoles:dashboard')

    if request.method == 'POST':
        nom = niveau.nom or NOM_NIVEAU_PAR_DEFAUT
        niveau.delete()
        messages.success(request, f'Niveau {nom} supprimé avec succès.')
        return redirect('ecoles:niveau_list')
    return render(request, 'ecoles/niveau_confirm_delete.html', {'niveau': niveau})


@login_required
def restore_niveau(request, pk):
    niveau = get_object_or_404(Niveau.all_objects, pk=pk, deleted_at__isnull=False)
    if not (request.user.est_administrateur() or request.user.est_agent()):
        messages.error(request, 'Accès non autorisé.')
        return redirect('ecoles:dashboard')
    niveau.restore()
    messages.success(request, f'Niveau "{niveau.nom or NOM_NIVEAU_PAR_DEFAUT}" restauré avec succès.')
    return redirect('ecoles:ecole_edit', pk=niveau.ecole.id)


@login_required
def niveau_affecter_ecole(request, pk):
    niveau_ref = get_object_or_404(Niveau, pk=pk, est_reference=True, ecole=None)
    user = request.user
    if user.est_parent() or user.est_ministre():
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
            messages.success(request, f'Le niveau {niveau_ref.nom or NOM_NIVEAU_PAR_DEFAUT} a été affecté à {ecole.nom} avec toutes ses classes et cours.')
        except Exception as e:
            messages.error(request, f'Erreur : {str(e)}')
        return redirect('ecoles:niveau_list')

    return render(request, 'ecoles/niveau_affecter.html', {
        'niveau': niveau_ref, 'ecole': ecole
    })


# ===================== SYNCHRONISATION =====================
@login_required
def synchroniser_niveau(request, pk):
    niveau = get_object_or_404(Niveau, pk=pk, est_reference=True, ecole__isnull=True)

    if not (request.user.est_administrateur() or request.user.est_agent()):
        messages.error(request, "Seuls les administrateurs et agents peuvent synchroniser les niveaux.")
        return redirect('ecoles:niveau_list')

    nb_instances = niveau.get_instances().count()
    nb_classes_ref = Classe.objects.filter(
        niveau=niveau, ecole__isnull=True, est_reference=True
    ).count()

    if request.method == 'POST':
        force_delete = request.POST.get('force_delete') == 'on'
        try:
            rapport = niveau.synchroniser_vers_ecoles(force_delete_notes=force_delete)
            rapport['force_delete_used'] = force_delete
            rapport['date_sync'] = timezone.now().strftime('%d/%m/%Y à %H:%M')
            rapport['utilisateur'] = request.user.get_full_name() or request.user.username
            rapport['action_source'] = "synchronisation manuelle"
            rapport['nb_ecoles_affectees'] = sum(
                1 for d in rapport.get('details_ecoles', [])
                if (d.get('classes_ajoutees', 0) + d.get('classes_modifiees', 0) +
                    d.get('cours_ajoutes', 0) + d.get('cours_modifies', 0) +
                    d.get('evaluations_ajoutees', 0) + d.get('evaluations_modifiees', 0) +
                    d.get('evaluations_supprimees', 0)) > 0
            )
            request.session['sync_rapport'] = rapport

            if rapport.get('success'):
                messages.success(
                    request,
                    f"Synchronisation réussie ! "
                    f"{rapport['instances_traitees']} école(s) traitée(s), "
                    f"{rapport['nb_ecoles_affectees']} école(s) affectée(s)."
                )
            else:
                messages.warning(
                    request,
                    f"Synchronisation partielle. "
                    f"{rapport.get('evaluations_bloquees', 0)} conflit(s) détecté(s)."
                )
            return redirect('ecoles:sync_report')
        except IntegrityError as e:
            messages.error(request, f"Erreur d'intégrité : {str(e)}")
            return redirect('ecoles:niveau_list')
        except Exception as e:
            logger.exception("Erreur de synchronisation")
            messages.error(request, f"Erreur inattendue : {str(e)}")
            return redirect('ecoles:niveau_list')

    context = {
        'niveau': niveau,
        'nb_instances': nb_instances,
        'nb_classes_ref': nb_classes_ref,
        'title': f'Synchroniser {niveau.nom or NOM_NIVEAU_PAR_DEFAUT}'
    }
    return render(request, 'ecoles/niveau_sync_confirm.html', context)


@login_required
def sync_report(request):
    rapport = request.session.pop('sync_rapport', None)
    if not rapport:
        messages.info(request, "Aucun rapport de synchronisation disponible.")
        return redirect('ecoles:niveau_list')

    if 'total_operations' not in rapport:
        rapport['total_operations'] = (
            rapport.get('classes_ajoutees', 0) + rapport.get('classes_modifiees', 0) +
            rapport.get('cours_ajoutes', 0) + rapport.get('cours_modifies', 0) +
            rapport.get('evaluations_ajoutees', 0) + rapport.get('evaluations_modifiees', 0) +
            rapport.get('evaluations_supprimees', 0)
        )

    rapport['nb_ecoles_avec_erreurs'] = sum(
        1 for d in rapport.get('details_ecoles', []) if d.get('erreurs')
    )

    if 'nb_ecoles_affectees' not in rapport:
        rapport['nb_ecoles_affectees'] = sum(
            1 for d in rapport.get('details_ecoles', [])
            if (d.get('classes_ajoutees', 0) + d.get('classes_modifiees', 0) +
                d.get('cours_ajoutes', 0) + d.get('cours_modifies', 0) +
                d.get('evaluations_ajoutees', 0) + d.get('evaluations_modifiees', 0) +
                d.get('evaluations_supprimees', 0)) > 0
        )

    context = {'rapport': rapport, 'title': 'Rapport de synchronisation'}
    return render(request, 'ecoles/niveau_sync_report.html', context)


# ===================== CRUD CLASSES =====================
@login_required
def classe_list(request):
    user = request.user
    if user.est_parent() or user.est_ministre():
        messages.warning(request, "Vous n'avez pas accès à cette liste.")
        return redirect('ecoles:dashboard')

    if user.est_enseignant():
        classes = Classe.objects.filter(id=user.classe_affectation.id, est_reference=False) if user.classe_affectation else Classe.objects.none()
    elif user.est_agent():
        classes = Classe.objects.all().order_by('-est_reference', 'nom')
    elif user.est_inspecteur():
        if user.ecole_affectation:
            classes = Classe.objects.filter(
                Q(est_reference=True) | Q(ecole=user.ecole_affectation, est_reference=False)
            )
        else:
            classes = Classe.objects.filter(est_reference=True)
    elif user.est_proved():
        if user.province_affectation:
            ecoles = Ecole.objects.filter(province=user.province_affectation)
            classes = Classe.objects.filter(
                Q(est_reference=True) | Q(ecole__in=ecoles, est_reference=False)
            )
        else:
            classes = Classe.objects.filter(est_reference=True)
    else:
        classes = Classe.objects.all().order_by('-est_reference', 'nom')

    ecole_id = request.GET.get('ecole')
    niveau_id = request.GET.get('niveau')
    if ecole_id:
        classes = classes.filter(ecole_id=ecole_id, est_reference=False)
    if niveau_id:
        classes = classes.filter(niveau_id=niveau_id)

    paginator = Paginator(classes, 20)
    page = request.GET.get('page')
    classes = paginator.get_page(page)

    if user.est_administrateur() or user.est_agent():
        ecoles = Ecole.objects.all()
        niveaux = Niveau.objects.filter(est_reference=False)
    elif user.est_inspecteur():
        ecoles = Ecole.objects.filter(id=user.ecole_affectation.id) if user.ecole_affectation else Ecole.objects.none()
        niveaux = Niveau.objects.filter(ecole=user.ecole_affectation, est_reference=False) if user.ecole_affectation else Niveau.objects.none()
    elif user.est_proved():
        if user.province_affectation:
            ecoles = Ecole.objects.filter(province=user.province_affectation)
            niveaux = Niveau.objects.filter(ecole__in=ecoles, est_reference=False)
        else:
            ecoles = Ecole.objects.none()
            niveaux = Niveau.objects.none()
    else:
        if user.ecole_affectation:
            ecoles = Ecole.objects.filter(id=user.ecole_affectation.id)
            niveaux = Niveau.objects.filter(ecole=user.ecole_affectation, est_reference=False)
        else:
            ecoles = Ecole.objects.none()
            niveaux = Niveau.objects.none()

    context = {
        'classes': classes, 'ecoles': ecoles, 'niveaux': niveaux,
        'selected_ecole': ecole_id, 'selected_niveau': niveau_id,
    }
    return render(request, 'ecoles/classe_list.html', context)


@login_required
def classe_create(request):
    if not (request.user.est_administrateur() or request.user.est_agent()):
        messages.error(request, 'Seuls les administrateurs et agents peuvent créer des classes de référence.')
        return redirect('ecoles:dashboard')
    if request.method == 'POST':
        form = ClasseForm(request.POST, user=request.user, is_reference=True)
        form.instance.est_reference = True
        if form.is_valid():
            classe = form.save(commit=False)
            classe.ecole = None
            classe.save()
            messages.success(request, f'Classe de référence {classe.nom} créée avec succès.')

            niveau = classe.niveau
            if niveau and niveau.est_reference:
                rapport = niveau.synchroniser_si_necessaire()
                if rapport:
                    _stocker_rapport_sync(request, rapport, "création de classe")
            return redirect('ecoles:classe_list')
    else:
        form = ClasseForm(user=request.user, is_reference=True)
        form.instance.est_reference = True
    return render(request, 'ecoles/classe_form.html', {'form': form, 'title': 'Créer une classe de référence'})


@login_required
def classe_edit(request, pk):
    classe = get_object_or_404(Classe, pk=pk)
    user = request.user
    if user.est_parent() or user.est_ministre():
        messages.error(request, 'Accès non autorisé.')
        return redirect('ecoles:dashboard')

    if classe.est_reference:
        if not (user.est_administrateur() or user.est_agent()):
            messages.error(request, 'Accès non autorisé.')
            return redirect('ecoles:dashboard')
        is_reference = True
    else:
        if user.est_agent():
            pass
        elif user.est_inspecteur() and classe.ecole != user.ecole_affectation:
            messages.error(request, 'Accès non autorisé.')
            return redirect('ecoles:dashboard')
        elif user.est_proved() and (classe.ecole and classe.ecole.province != user.province_affectation):
            messages.error(request, 'Accès non autorisé.')
            return redirect('ecoles:dashboard')
        is_reference = False

    if request.method == 'POST':
        form = ClasseForm(request.POST, instance=classe, user=user, is_reference=is_reference)
        if form.is_valid():
            classe = form.save()
            messages.success(request, 'Classe modifiée avec succès.')
            if is_reference:
                niveau = classe.niveau
                if niveau and niveau.est_reference:
                    rapport = niveau.synchroniser_si_necessaire()
                    if rapport:
                        _stocker_rapport_sync(request, rapport, "modification de classe")
            return redirect('ecoles:classe_list')
    else:
        form = ClasseForm(instance=classe, user=user, is_reference=is_reference)
    return render(request, 'ecoles/classe_form.html', {'form': form, 'title': 'Modifier une classe'})


@login_required
def classe_delete(request, pk):
    classe = get_object_or_404(Classe, pk=pk)
    user = request.user
    if user.est_parent() or user.est_ministre():
        messages.error(request, 'Accès non autorisé.')
        return redirect('ecoles:dashboard')

    if classe.est_reference:
        if not (user.est_administrateur() or user.est_agent()):
            messages.error(request, 'Accès non autorisé.')
            return redirect('ecoles:dashboard')
    else:
        if user.est_agent():
            pass
        elif user.est_inspecteur() and classe.ecole != user.ecole_affectation:
            messages.error(request, 'Accès non autorisé.')
            return redirect('ecoles:dashboard')
        elif user.est_proved() and (classe.ecole and classe.ecole.province != user.province_affectation):
            messages.error(request, 'Accès non autorisé.')
            return redirect('ecoles:dashboard')

    if request.method == 'POST':
        nom = classe.nom
        classe.delete()
        messages.success(request, f'Classe {nom} supprimée avec succès.')
        return redirect('ecoles:classe_list')
    return render(request, 'ecoles/classe_confirm_delete.html', {'classe': classe})


# ===================== DUPLICATION DE CLASSE =====================
@login_required
def classe_duplicate(request, pk):
    source_classe = get_object_or_404(Classe, pk=pk, est_reference=False)
    user = request.user

    if user.est_parent() or user.est_ministre():
        messages.error(request, 'Accès non autorisé.')
        return redirect('ecoles:dashboard')

    if user.est_agent():
        pass
    elif user.est_inspecteur():
        if source_classe.ecole != user.ecole_affectation:
            messages.error(request, 'Accès non autorisé.')
            return redirect('ecoles:dashboard')
    elif user.est_proved():
        if source_classe.ecole.province != user.province_affectation:
            messages.error(request, 'Accès non autorisé.')
            return redirect('ecoles:dashboard')

    if request.method == 'POST':
        form = ClasseDuplicateForm(
            request.POST,
            source_classe=source_classe,
            ecole=source_classe.ecole,
            niveau=source_classe.niveau,
        )
        if form.is_valid():
            nouveau_nom = form.cleaned_data['nouveau_nom']
            classe_ref = None

            try:
                with transaction.atomic():
                    niveau_ref = source_classe.niveau.reference_source
                    if not niveau_ref:
                        niveau_ref = Niveau.objects.filter(
                            nom=source_classe.niveau.nom,
                            section=source_classe.niveau.section,
                            est_reference=True,
                            ecole__isnull=True,
                        ).first()

                    if not niveau_ref:
                        messages.error(
                            request,
                            f"Impossible de trouver la référence pour le niveau "
                            f"'{source_classe.niveau.nom or NOM_NIVEAU_PAR_DEFAUT}'. Contactez l'administrateur."
                        )
                        return redirect('ecoles:classe_list')

                    classe_ref = Classe.objects.filter(
                        nom=nouveau_nom,
                        niveau=niveau_ref,
                        est_reference=True,
                        ecole__isnull=True,
                    ).first()

                    if not classe_ref:
                        classe_ref = Classe.objects.create(
                            nom=nouveau_nom,
                            description=source_classe.description,
                            ordre=source_classe.ordre,
                            niveau=niveau_ref,
                            ecole=None,
                            est_reference=True,
                        )
                        messages.info(request, f"📚 Classe de référence '{nouveau_nom}' créée.")

                        cours_source = Cours.objects.filter(
                            classe=source_classe,
                            est_reference=False,
                        )
                        for cours in cours_source:
                            base_code = cours.code
                            code_ref = base_code.replace(f"_{source_classe.nom}", "")
                            if not code_ref:
                                code_ref = base_code
                            code_candidat = code_ref
                            suffix = 1
                            while Cours.objects.filter(code=code_candidat).exists():
                                code_candidat = f"{code_ref}_ref_{suffix}"
                                suffix += 1

                            nouveau_cours_ref = Cours.objects.create(
                                nom=cours.nom,
                                code=code_candidat,
                                coefficient=cours.coefficient,
                                description=cours.description,
                                niveau=niveau_ref,
                                classe=classe_ref,
                                ecole=None,
                                est_reference=True,
                            )

                            cycle_source, _ = CycleEvaluation.objects.get_or_create(cours=cours)
                            if not cycle_source.evaluations.exists():
                                cycle_source.creer_evaluations_par_defaut()

                            nouveau_cycle_ref = CycleEvaluation.objects.create(
                                cours=nouveau_cours_ref,
                                type_cycle=cycle_source.type_cycle,
                            )
                            for config in cycle_source.evaluations.all():
                                EvaluationConfig.objects.create(
                                    cycle_evaluation=nouveau_cycle_ref,
                                    cycle_num=config.cycle_num,
                                    periode_num=config.periode_num,
                                    type=config.type,
                                    points_max=config.points_max,
                                    ordre=config.ordre,
                                )

                    nouvelle_classe = Classe.objects.create(
                        nom=nouveau_nom,
                        description=source_classe.description,
                        ordre=source_classe.ordre,
                        niveau=source_classe.niveau,
                        ecole=source_classe.ecole,
                        est_reference=False,
                        reference_source=classe_ref,
                    )

                    cours_source = Cours.objects.filter(
                        classe=source_classe,
                        est_reference=False,
                    )
                    for cours in cours_source:
                        cours_ref = Cours.objects.filter(
                            nom=cours.nom,
                            classe=classe_ref,
                            est_reference=True,
                            ecole__isnull=True,
                        ).first()

                        base_code = cours.code
                        code_candidat = base_code
                        suffix = 1
                        while Cours.objects.filter(code=code_candidat).exists():
                            code_candidat = f"{base_code}_{suffix}"
                            suffix += 1

                        nouveau_cours = Cours.objects.create(
                            nom=cours.nom,
                            code=code_candidat,
                            coefficient=cours.coefficient,
                            description=cours.description,
                            niveau=cours.niveau,
                            classe=nouvelle_classe,
                            ecole=cours.ecole,
                            est_reference=False,
                            reference_source=cours_ref,
                        )

                        cycle_source, _ = CycleEvaluation.objects.get_or_create(cours=cours)
                        if not cycle_source.evaluations.exists():
                            cycle_source.creer_evaluations_par_defaut()

                        nouveau_cycle = CycleEvaluation.objects.create(
                            cours=nouveau_cours,
                            type_cycle=cycle_source.type_cycle,
                        )
                        for config in cycle_source.evaluations.all():
                            EvaluationConfig.objects.create(
                                cycle_evaluation=nouveau_cycle,
                                cycle_num=config.cycle_num,
                                periode_num=config.periode_num,
                                type=config.type,
                                points_max=config.points_max,
                                ordre=config.ordre,
                            )

            except Exception as e:
                logger.exception("Erreur de duplication")
                messages.error(request, f"Erreur lors de la duplication : {str(e)}")
                return redirect('ecoles:classe_list')

            if classe_ref:
                cours_ref_qs = Cours.objects.filter(
                    classe=classe_ref,
                    ecole=None,
                    est_reference=True,
                )
                for cours_ref in cours_ref_qs:
                    rapport = synchroniser_cours_ref_vers_instances(
                        cours_ref, logger=logger
                    )
                    if rapport and rapport.get('instances_traitees', 0) > 0:
                        _stocker_rapport_sync(
                            request, rapport,
                            f"duplication de classe ({nouveau_nom})"
                        )

            messages.success(
                request,
                f"✅ Classe '{source_classe.nom}' dupliquée en '{nouveau_nom}' "
                f"avec ses cours. La référence a été mise à jour."
            )
            return redirect('ecoles:classe_list')
    else:
        form = ClasseDuplicateForm(
            source_classe=source_classe,
            ecole=source_classe.ecole,
            niveau=source_classe.niveau,
        )
        form.fields['nouveau_nom'].initial = f"{source_classe.nom} (copie)"

    return render(request, 'ecoles/classe_duplicate.html', {
        'form': form,
        'source_classe': source_classe,
        'title': 'Dupliquer une classe',
    })


# ===================== CRUD COURS =====================
@login_required
def cours_list(request):
    user = request.user
    if user.est_parent() or user.est_ministre():
        messages.warning(request, "Vous n'avez pas accès à cette liste.")
        return redirect('ecoles:dashboard')

    if user.est_enseignant():
        if user.classe_affectation:
            cours_qs = Cours.objects.filter(classe=user.classe_affectation, est_reference=False)
        else:
            cours_qs = Cours.objects.none()
    elif user.est_agent():
        cours_qs = Cours.objects.all()
    elif user.est_inspecteur():
        if user.ecole_affectation:
            cours_qs = Cours.objects.filter(Q(est_reference=True) | Q(ecole=user.ecole_affectation, est_reference=False))
        else:
            cours_qs = Cours.objects.filter(est_reference=True)
    elif user.est_proved():
        if user.province_affectation:
            ecoles = Ecole.objects.filter(province=user.province_affectation)
            cours_qs = Cours.objects.filter(Q(est_reference=True) | Q(ecole__in=ecoles, est_reference=False))
        else:
            cours_qs = Cours.objects.filter(est_reference=True)
    else:
        cours_qs = Cours.objects.all()

    ecole_id = request.GET.get('ecole')
    niveau_id = request.GET.get('niveau')
    classe_id = request.GET.get('classe')
    type_filter = request.GET.get('type')
    search_query = request.GET.get('q', '').strip()

    if ecole_id: cours_qs = cours_qs.filter(ecole_id=ecole_id, est_reference=False)
    if niveau_id: cours_qs = cours_qs.filter(niveau_id=niveau_id)
    if classe_id: cours_qs = cours_qs.filter(classe_id=classe_id)
    if type_filter == 'reference': cours_qs = cours_qs.filter(est_reference=True)
    elif type_filter == 'instance': cours_qs = cours_qs.filter(est_reference=False)
    if search_query:
        cours_qs = cours_qs.filter(Q(nom__icontains=search_query) | Q(code__icontains=search_query))

    cours_qs = cours_qs.select_related('niveau', 'classe', 'ecole')

    nb_filtres_actifs = sum([
        bool(ecole_id), bool(niveau_id), bool(classe_id),
        bool(type_filter), bool(search_query),
    ])

    try:
        cours_recents = list(cours_qs.order_by('-date_creation', '-pk')[:8])
    except Exception:
        cours_recents = list(cours_qs.order_by('-pk')[:8])

    groupes_dict = defaultdict(list)
    for c in cours_qs:
        key = (c.nom, c.niveau_id, c.ecole_id, c.est_reference)
        groupes_dict[key].append(c)

    cours_groupes = []
    for key, liste_cours in groupes_dict.items():
        liste_triees = sorted(liste_cours, key=lambda x: x.classe.nom if x.classe else '')
        premier = liste_triees[0]
        codes = list(dict.fromkeys([c.code for c in liste_triees]))
        classes_info = [{'classe': c.classe, 'cours_id': c.pk, 'code': c.code} for c in liste_triees]
        coefficients = list(dict.fromkeys([c.coefficient for c in liste_triees]))

        dates = []
        for c in liste_triees:
            d = getattr(c, 'date_creation', None)
            if d: dates.append(d)
        date_recente = max(dates) if dates else None

        cours_groupes.append({
            'nom': premier.nom, 'description': premier.description,
            'niveau': premier.niveau,
            'ecole': premier.ecole, 'est_reference': premier.est_reference,
            'codes': codes, 'codes_str': ', '.join(codes),
            'coefficients': coefficients,
            'coefficient_unique': coefficients[0] if len(coefficients) == 1 else None,
            'coefficients_str': ' / '.join(str(x) for x in coefficients),
            'classes_info': classes_info, 'nb_classes': len(classes_info),
            'cours_principal_id': premier.pk,
            'cours_ids': [c.pk for c in liste_triees],
            'cours_ids_str': ','.join(str(c.pk) for c in liste_triees),
            'date_recente': date_recente,
            'pk_max': max(c.pk for c in liste_triees) if liste_triees else 0,
            'instances': liste_triees,
        })

    def tri_key(g):
        date_val = g['date_recente']
        ts = -date_val.timestamp() if date_val else -g['pk_max']
        return (0 if g['est_reference'] else 1, ts, g['nom'].lower())

    cours_groupes.sort(key=tri_key)

    paginator = Paginator(cours_groupes, 15)
    page = request.GET.get('page')
    cours_page = paginator.get_page(page)

    query_params = ''
    if ecole_id: query_params += f'&ecole={ecole_id}'
    if niveau_id: query_params += f'&niveau={niveau_id}'
    if classe_id: query_params += f'&classe={classe_id}'
    if type_filter: query_params += f'&type={type_filter}'
    if search_query: query_params += f'&q={search_query}'

    if user.est_administrateur() or user.est_agent():
        ecoles = Ecole.objects.all()
        niveaux = Niveau.objects.filter(est_reference=False)
        classes = Classe.objects.filter(est_reference=False)
    elif user.est_inspecteur():
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
        if user.ecole_affectation:
            ecoles = Ecole.objects.filter(id=user.ecole_affectation.id)
            niveaux = Niveau.objects.filter(ecole=user.ecole_affectation, est_reference=False)
            classes = Classe.objects.filter(ecole=user.ecole_affectation, est_reference=False)
        else:
            ecoles = Ecole.objects.none()
            niveaux = Niveau.objects.none()
            classes = Classe.objects.none()

    context = {
        'cours_page': cours_page, 'cours_recents': cours_recents,
        'ecoles': ecoles, 'niveaux': niveaux, 'classes': classes,
        'selected_ecole': ecole_id, 'selected_niveau': niveau_id,
        'selected_classe': classe_id,
        'selected_type': type_filter, 'search_query': search_query,
        'query_params': query_params, 'nb_filtres_actifs': nb_filtres_actifs,
        'total_groupes': len(cours_groupes), 'total_cours': cours_qs.count(),
    }
    return render(request, 'ecoles/cours_list.html', context)


@login_required
def cours_create(request):
    user = request.user
    if not (user.est_administrateur() or user.est_agent()):
        messages.error(request, 'Accès non autorisé.')
        return redirect('ecoles:dashboard')

    is_reference = True
    if user.est_administrateur():
        ref_param = request.GET.get('ref', '1')
        is_reference = (ref_param == '1')
    elif user.est_agent():
        is_reference = True

    if request.method == 'POST':
        form = CoursForm(request.POST, user=request.user, is_reference=is_reference)
        form.instance.est_reference = is_reference
        cycle_config_form = CycleEvaluationConfigForm(
            request.POST, user=request.user, is_reference=is_reference
        )

        if form.is_valid():
            nom = form.cleaned_data['nom']
            base_code = form.cleaned_data['code']
            coefficient = form.cleaned_data['coefficient']
            description = form.cleaned_data.get('description', '')
            niveau = form.cleaned_data['niveau']
            classes = form.cleaned_data['classe']
            ecole = None if is_reference else form.cleaned_data.get('ecole')

            config_data = cycle_config_form.get_config()

            created_cours = []
            errors = []

            for classe in classes:
                code_candidat = base_code
                suffix = 1
                while Cours.objects.filter(code=code_candidat).exists():
                    code_candidat = f"{base_code}_{suffix}"
                    suffix += 1

                try:
                    with transaction.atomic():
                        cours = Cours.objects.create(
                            nom=nom, code=code_candidat, coefficient=coefficient,
                            description=description, niveau=niveau, classe=classe,
                            ecole=None if is_reference else ecole,
                            est_reference=is_reference,
                        )
                        cycle_eval = CycleEvaluation.objects.create(
                            cours=cours,
                            type_cycle=config_data['type_cycle'] if config_data else 'trimestre'
                        )
                        cycle_eval.evaluations.all().delete()

                        if config_data:
                            nb_cycles = config_data['nombre_cycles']
                            nb_periodes = config_data['periodes_par_cycle']
                            inclure_examen = config_data['inclure_examen']
                            pts_max = config_data['points_max']
                            pts_max_examen = pts_max * 2

                            for cycle_num in range(1, nb_cycles + 1):
                                for periode_num in range(1, nb_periodes + 1):
                                    EvaluationConfig.objects.create(
                                        cycle_evaluation=cycle_eval, cycle_num=cycle_num,
                                        periode_num=periode_num, type='periode',
                                        points_max=pts_max, ordre=periode_num
                                    )
                                if inclure_examen:
                                    EvaluationConfig.objects.create(
                                        cycle_evaluation=cycle_eval, cycle_num=cycle_num,
                                        periode_num=None, type='examen',
                                        points_max=pts_max_examen, ordre=nb_periodes + 1
                                    )
                        else:
                            cycle_eval.creer_evaluations_par_defaut()

                        created_cours.append(cours)
                except Exception as e:
                    errors.append(f"{classe.nom} : {str(e)}")

            if created_cours:
                if len(created_cours) == 1:
                    messages.success(request, f'Cours "{nom}" créé avec succès.')
                else:
                    messages.success(request, f'{len(created_cours)} cours "{nom}" créés avec succès.')

                if is_reference:
                    logger.info(f"[cours_create] {len(created_cours)} cours de référence créés")
                    for cours_ref in created_cours:
                        if cours_ref.classe and cours_ref.classe.est_reference:
                            rapport = synchroniser_cours_ref_vers_instances(
                                cours_ref, logger=logger
                            )
                            if rapport and rapport.get('instances_traitees', 0) > 0:
                                _stocker_rapport_sync(
                                    request, rapport,
                                    f"création de cours ({cours_ref.nom})"
                                )

            if errors:
                for err in errors:
                    messages.warning(request, err)
            return redirect('ecoles:cours_list')
    else:
        form = CoursForm(user=request.user, is_reference=is_reference)
        form.instance.est_reference = is_reference
        cycle_config_form = CycleEvaluationConfigForm(user=request.user, is_reference=is_reference)

    title = 'Créer un cours de référence' if is_reference else 'Créer un cours'
    return render(request, 'ecoles/cours_form.html', {
        'form': form, 'cycle_config_form': cycle_config_form,
        'title': title, 'is_edit': False,
        'is_reference_form': is_reference,
    })


@login_required
def cours_edit(request, pk):
    cours = get_object_or_404(Cours, pk=pk)
    user = request.user

    if user.est_parent() or user.est_ministre():
        messages.error(request, 'Accès non autorisé.')
        return redirect('ecoles:dashboard')

    if user.est_agent() and not cours.est_reference:
        messages.error(request, "En tant qu'agent, vous ne pouvez modifier que les cours de référence.")
        return redirect('ecoles:cours_list')

    if cours.est_reference:
        if not (user.est_administrateur() or user.est_agent()):
            messages.error(request, 'Accès non autorisé.')
            return redirect('ecoles:dashboard')
        is_reference = True
    else:
        if user.est_agent():
            pass
        elif user.est_inspecteur() and cours.ecole != user.ecole_affectation:
            messages.error(request, 'Accès non autorisé.')
            return redirect('ecoles:dashboard')
        elif user.est_proved() and (cours.ecole and cours.ecole.province != user.province_affectation):
            messages.error(request, 'Accès non autorisé.')
            return redirect('ecoles:dashboard')
        is_reference = False

    cycle_eval, created = CycleEvaluation.objects.get_or_create(cours=cours)

    if request.method == 'POST':
        form = CoursForm(request.POST, instance=cours, user=user, is_reference=is_reference)
        cycle_form = CycleEvaluationForm(request.POST, instance=cycle_eval)
        formset = EvaluationConfigFormSet(request.POST, instance=cycle_eval)

        if form.is_valid() and cycle_form.is_valid() and formset.is_valid():
            classes = list(form.cleaned_data.get('classe') or [])

            if not classes:
                messages.error(request, 'Veuillez sélectionner au moins une classe.')
                return render(request, 'ecoles/cours_form.html', {
                    'form': form, 'cycle_form': cycle_form, 'formset': formset,
                    'cours': cours, 'title': 'Modifier un cours', 'is_edit': True,
                    'is_reference_form': is_reference,
                })

            first_classe = classes[0]

            try:
                with transaction.atomic():
                    cours.nom = form.cleaned_data['nom']
                    cours.code = form.cleaned_data['code']
                    cours.coefficient = form.cleaned_data['coefficient']
                    cours.description = form.cleaned_data.get('description', '')
                    cours.niveau = form.cleaned_data['niveau']
                    cours.classe = first_classe
                    cours.ecole = None if is_reference else form.cleaned_data.get('ecole')
                    cours.est_reference = is_reference
                    cours.save()

                    cycle_form.save()
                    formset.save()
                    cycle_eval.nettoyer_evaluations()

                    configs_source = list(cycle_eval.evaluations.all().order_by('cycle_num', 'ordre'))

                    created_count = 0
                    base_code = cours.code
                    existing_combos = {(first_classe.id,)}

                    for classe in classes:
                        if (classe.id,) in existing_combos:
                            continue
                        code_candidat = base_code
                        suffix = 1
                        while Cours.objects.filter(code=code_candidat).exists():
                            code_candidat = f"{base_code}_{suffix}"
                            suffix += 1
                        nouveau_cours = Cours.objects.create(
                            nom=cours.nom, code=code_candidat, coefficient=cours.coefficient,
                            description=cours.description, niveau=cours.niveau,
                            classe=classe, ecole=cours.ecole,
                            est_reference=cours.est_reference,
                            reference_source=cours.reference_source,
                        )
                        nouveau_cycle = CycleEvaluation.objects.create(
                            cours=nouveau_cours, type_cycle=cycle_eval.type_cycle
                        )
                        nouveau_cycle.evaluations.all().delete()
                        for config in configs_source:
                            EvaluationConfig.objects.create(
                                cycle_evaluation=nouveau_cycle,
                                cycle_num=config.cycle_num, periode_num=config.periode_num,
                                type=config.type, points_max=config.points_max,
                                ordre=config.ordre
                            )
                        created_count += 1

            except Exception as e:
                logger.exception("Erreur cours_edit")
                messages.error(request, f"Erreur lors de la modification : {str(e)}")
                return render(request, 'ecoles/cours_form.html', {
                    'form': form, 'cycle_form': cycle_form, 'formset': formset,
                    'cours': cours, 'title': 'Modifier un cours', 'is_edit': True,
                    'is_reference_form': is_reference,
                })

            if created_count > 0:
                messages.success(request, f'Cours "{cours.nom}" modifié + {created_count} nouveau(x) cours créé(s).')
            else:
                messages.success(request, 'Cours modifié avec succès.')

            if is_reference and cours.classe and cours.classe.est_reference:
                rapport = synchroniser_cours_ref_vers_instances(
                    cours, logger=logger
                )
                if rapport and rapport.get('instances_traitees', 0) > 0:
                    _stocker_rapport_sync(
                        request, rapport,
                        f"modification de cours ({cours.nom})"
                    )

            return redirect('ecoles:cours_list')
    else:
        form = CoursForm(instance=cours, user=user, is_reference=is_reference)
        cycle_form = CycleEvaluationForm(instance=cycle_eval)
        formset = EvaluationConfigFormSet(instance=cycle_eval)

    context = {
        'form': form, 'cycle_form': cycle_form, 'formset': formset,
        'cours': cours, 'title': 'Modifier un cours', 'is_edit': True,
        'is_reference_form': is_reference,
    }
    return render(request, 'ecoles/cours_form.html', context)


@login_required
def cours_delete(request, pk):
    cours = get_object_or_404(Cours, pk=pk)
    user = request.user
    if user.est_parent() or user.est_ministre():
        messages.error(request, 'Accès non autorisé.')
        return redirect('ecoles:dashboard')

    if user.est_agent() and not cours.est_reference:
        messages.error(request, "En tant qu'agent, vous ne pouvez supprimer que les cours de référence.")
        return redirect('ecoles:cours_list')

    if cours.est_reference:
        if not (user.est_administrateur() or user.est_agent()):
            messages.error(request, 'Accès non autorisé.')
            return redirect('ecoles:dashboard')
    else:
        if user.est_agent():
            pass
        elif user.est_inspecteur() and cours.ecole != user.ecole_affectation:
            messages.error(request, 'Accès non autorisé.')
            return redirect('ecoles:dashboard')
        elif user.est_proved() and (cours.ecole and cours.ecole.province != user.province_affectation):
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


# ===================== CRUD SECTIONS =====================
@login_required
def section_list(request):
    user = request.user
    if user.est_parent():
        messages.error(request, "Accès non autorisé.")
        return redirect('ecoles:dashboard')

    readonly = user.est_ministre() or user.est_inspecteur() or user.est_proved() or user.est_enseignant()

    sections = Section.objects.all().order_by('ordre', 'nom')
    paginator = Paginator(sections, 20)
    page = request.GET.get('page')
    sections = paginator.get_page(page)

    context = {
        'sections': sections,
        'readonly': readonly,
    }
    return render(request, 'ecoles/section_list.html', context)


@login_required
def section_create(request):
    if not (request.user.est_administrateur() or request.user.est_agent()):
        messages.error(request, 'Seuls les administrateurs et agents peuvent créer des sections.')
        return redirect('ecoles:dashboard')
    if request.method == 'POST':
        form = SectionForm(request.POST)
        if form.is_valid():
            section = form.save(commit=False)
            if not section.nom or not section.nom.strip():
                section.nom = NOM_SECTION_PAR_DEFAUT
            section.save()
            messages.success(request, f'Section "{section.nom}" créée avec succès.')
            return redirect('ecoles:section_list')
    else:
        form = SectionForm()
    return render(request, 'ecoles/section_form.html', {'form': form, 'title': 'Créer une section'})


@login_required
def section_edit(request, pk):
    if not (request.user.est_administrateur() or request.user.est_agent()):
        messages.error(request, 'Seuls les administrateurs et agents peuvent modifier des sections.')
        return redirect('ecoles:dashboard')
    section = get_object_or_404(Section, pk=pk)
    if request.method == 'POST':
        form = SectionForm(request.POST, instance=section)
        if form.is_valid():
            section = form.save(commit=False)
            if not section.nom or not section.nom.strip():
                section.nom = NOM_SECTION_PAR_DEFAUT
            section.save()
            messages.success(request, f'Section "{section.nom}" modifiée avec succès.')
            return redirect('ecoles:section_list')
    else:
        form = SectionForm(instance=section)
    return render(request, 'ecoles/section_form.html', {'form': form, 'title': 'Modifier une section'})


@login_required
def section_delete(request, pk):
    if not (request.user.est_administrateur() or request.user.est_agent()):
        messages.error(request, 'Seuls les administrateurs et agents peuvent supprimer des sections.')
        return redirect('ecoles:dashboard')
    section = get_object_or_404(Section, pk=pk)
    if request.method == 'POST':
        nom = section.nom or NOM_SECTION_PAR_DEFAUT
        section.delete()
        messages.success(request, f'Section "{nom}" supprimée avec succès.')
        return redirect('ecoles:section_list')
    return render(request, 'ecoles/section_confirm_delete.html', {'section': section})


# ===================== RÉSULTATS =====================
@login_required
def resultat_list(request):
    user = request.user
    if user.est_parent() or user.est_ministre() or user.est_agent():
        messages.warning(request, "Vous n'avez pas accès à cette liste.")
        return redirect('ecoles:dashboard')

    resultats = EvaluationResultat.objects.all()
    if user.est_enseignant():
        if user.classe_affectation:
            resultats = resultats.filter(eleve__classe=user.classe_affectation)
        else:
            resultats = resultats.none()
    elif user.est_inspecteur():
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

    if ecole_id: resultats = resultats.filter(eleve__ecole_id=ecole_id)
    if niveau_id: resultats = resultats.filter(eleve__niveau_id=niveau_id)
    if classe_id: resultats = resultats.filter(eleve__classe_id=classe_id)
    if cours_id: resultats = resultats.filter(cours_id=cours_id)
    if annee_id: resultats = resultats.filter(annee_scolaire_id=annee_id)

    if statut == 'reussite':
        resultats = resultats.filter(points_obtenus__gte=0.5 * F('evaluation_config__points_max'))
    elif statut == 'echec':
        resultats = resultats.filter(points_obtenus__lt=0.5 * F('evaluation_config__points_max'))

    eleves_sans_note = None
    if sans_note and cours_id and annee_id:
        eleves_avec_note = EvaluationResultat.objects.filter(
            cours_id=cours_id, annee_scolaire_id=annee_id
        ).values_list('eleve_id', flat=True).distinct()
        eleves_queryset = Eleve.objects.all()
        if user.est_enseignant() and user.classe_affectation:
            eleves_queryset = eleves_queryset.filter(classe=user.classe_affectation)
        elif user.est_inspecteur():
            eleves_queryset = eleves_queryset.filter(ecole=user.ecole_affectation)
        elif user.est_proved() and user.province_affectation:
            ecoles = Ecole.objects.filter(province=user.province_affectation)
            eleves_queryset = eleves_queryset.filter(ecole__in=ecoles)
        if ecole_id: eleves_queryset = eleves_queryset.filter(ecole_id=ecole_id)
        if niveau_id: eleves_queryset = eleves_queryset.filter(niveau_id=niveau_id)
        if classe_id: eleves_queryset = eleves_queryset.filter(classe_id=classe_id)
        eleves_sans_note = eleves_queryset.exclude(id__in=eleves_avec_note)

    resultats = resultats.select_related(
        'eleve', 'cours', 'annee_scolaire', 'evaluation_config'
    ).order_by('-date_saisie')

    paginator = Paginator(resultats, 20)
    page = request.GET.get('page')
    resultats_page = paginator.get_page(page)

    if user.est_enseignant():
        ecoles = Ecole.objects.filter(id=user.ecole_affectation.id) if user.ecole_affectation else Ecole.objects.none()
        niveaux = Niveau.objects.filter(ecole=user.ecole_affectation, est_reference=False) if user.ecole_affectation else Niveau.objects.none()
        classes = Classe.objects.filter(id=user.classe_affectation.id) if user.classe_affectation else Classe.objects.none()
        cours = Cours.objects.filter(classe=user.classe_affectation, est_reference=False) if user.classe_affectation else Cours.objects.none()
    elif user.est_inspecteur():
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
        'resultats': resultats_page, 'eleves_sans_note': eleves_sans_note,
        'ecoles': ecoles, 'niveaux': niveaux, 'classes': classes, 'cours': cours,
        'annees': AnneeScolaire.objects.all(),
        'selected_ecole': ecole_id, 'selected_niveau': niveau_id,
        'selected_classe': classe_id, 'selected_cours': cours_id,
        'selected_annee': annee_id,
    }
    return render(request, 'ecoles/resultat_list.html', context)


@login_required
def resultat_create(request):
    user = request.user
    if user.est_parent() or user.est_ministre() or user.est_agent():
        messages.error(request, 'Vous n\'avez pas les droits pour saisir des résultats.')
        return redirect('ecoles:resultat_list')

    if not (user.est_administrateur() or user.est_inspecteur()
            or user.est_proved() or user.est_enseignant()):
        messages.error(request, 'Accès non autorisé.')
        return redirect('ecoles:resultat_list')

    if request.method == 'GET' and not (request.GET.get('eleve') and request.GET.get('cours') and request.GET.get('annee_scolaire')):
        selection_form = ResultatSelectionForm(user=request.user)
        return render(request, 'ecoles/resultat_form.html', {
            'selection_form': selection_form, 'title': 'Saisie des résultats'
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

    if cours.ecole_id and eleve.ecole_id and cours.ecole_id != eleve.ecole_id:
        messages.error(
            request,
            f"Le cours '{cours.nom}' appartient à une autre école ({cours.ecole.nom}). "
            f"Veuillez sélectionner un cours de {eleve.ecole.nom}."
        )
        return redirect('ecoles:resultat_create')

    if user.est_enseignant():
        if not user.classe_affectation or eleve.classe != user.classe_affectation:
            messages.error(request, 'Vous ne pouvez saisir que pour votre classe.')
            return redirect('ecoles:resultat_list')
    elif user.est_inspecteur() and (eleve.ecole != user.ecole_affectation or cours.ecole != user.ecole_affectation):
        messages.error(request, 'Accès non autorisé.')
        return redirect('ecoles:dashboard')
    elif user.est_proved() and (eleve.ecole.province != user.province_affectation or cours.ecole.province != user.province_affectation):
        messages.error(request, 'Accès non autorisé.')
        return redirect('ecoles:dashboard')

    if cours.est_reference:
        messages.error(request, 'Vous ne pouvez pas saisir de notes pour un cours de référence.')
        return redirect('ecoles:resultat_list')

    cycle_eval, created = CycleEvaluation.objects.get_or_create(cours=cours)
    if created:
        cycle_eval.creer_evaluations_par_defaut()
        messages.info(request, "Configuration d'évaluation par défaut créée.")
    else:
        cycle_eval.nettoyer_evaluations()
        cycle_eval.refresh_from_db()
        nb_cycles = cycle_eval.get_nombre_cycles()
        cycles_existants = cycle_eval.evaluations.values('cycle_num').distinct().count()
        if cycles_existants != nb_cycles:
            cycle_eval.evaluations.all().delete()
            cycle_eval.creer_evaluations_par_defaut()
            messages.warning(request, "Les évaluations ont été réinitialisées car le type de cycle a changé.")
        else:
            cycle_eval.nettoyer_evaluations()

    nb_cycles = cycle_eval.get_nombre_cycles()
    configs_finales = cycle_eval.evaluations.filter(cycle_num__lte=nb_cycles).order_by('cycle_num', 'ordre')

    resultats_existants = EvaluationResultat.objects.filter(
        eleve=eleve, cours=cours, annee_scolaire=annee
    ).select_related('evaluation_config').order_by('evaluation_config__cycle_num', 'evaluation_config__ordre')

    resultats_par_cycle = {}
    for r in resultats_existants:
        cycle_num = r.evaluation_config.cycle_num
        resultats_par_cycle.setdefault(cycle_num, []).append(r)

    if request.method == 'POST':
        form = EvaluationResultatForm(eleve, cours, annee, user=request.user, data=request.POST, configs=configs_finales)
        if form.is_valid():
            form.save()
            recalculer_resultats_eleve(eleve, annee)
            messages.success(request, 'Résultats enregistrés avec succès.')
            return redirect('ecoles:resultat_list')
    else:
        form = EvaluationResultatForm(eleve, cours, annee, user=request.user, configs=configs_finales)

    for field_name, field in form.fields.items():
        if field_name.startswith('eval_'):
            config_id = getattr(field, 'config_id', None)
            if config_id:
                try:
                    config = EvaluationConfig.objects.get(pk=config_id)
                    field.config = config
                    field.cycle_num = config.cycle_num
                    field.periode_num = config.periode_num
                    field.eval_type = config.type
                    field.points_max = config.points_max
                except EvaluationConfig.DoesNotExist:
                    pass

    context = {
        'form': form, 'eleve': eleve, 'cours': cours, 'annee': annee,
        'title': 'Saisie des résultats',
        'resultats_existants': resultats_existants,
        'resultats_par_cycle': resultats_par_cycle,
        'configs': configs_finales,
    }
    return render(request, 'ecoles/resultat_form.html', context)


@login_required
def resultat_edit(request, pk):
    resultat = get_object_or_404(EvaluationResultat, pk=pk)
    user = request.user
    if user.est_parent() or user.est_ministre() or user.est_agent():
        messages.error(request, 'Accès non autorisé.')
        return redirect('ecoles:dashboard')
    elif user.est_enseignant():
        if not user.classe_affectation or resultat.eleve.classe != user.classe_affectation:
            messages.error(request, 'Accès non autorisé.')
            return redirect('ecoles:dashboard')
    elif user.est_inspecteur() and resultat.eleve.ecole != user.ecole_affectation:
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
    if user.est_parent() or user.est_ministre() or user.est_agent():
        messages.error(request, 'Accès non autorisé.')
        return redirect('ecoles:dashboard')
    elif user.est_enseignant():
        if not user.classe_affectation or resultat.eleve.classe != user.classe_affectation:
            messages.error(request, 'Accès non autorisé.')
            return redirect('ecoles:dashboard')
    elif user.est_inspecteur() and resultat.eleve.ecole != user.ecole_affectation:
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
    if user.est_parent() or user.est_ministre() or user.est_agent():
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
    elif user.est_inspecteur():
        eleves = Eleve.objects.filter(ecole=user.ecole_affectation) if user.ecole_affectation else Eleve.objects.none()
    elif user.est_proved():
        if user.province_affectation:
            ecoles = Ecole.objects.filter(province=user.province_affectation)
            eleves = Eleve.objects.filter(ecole__in=ecoles)
        else:
            eleves = Eleve.objects.none()
    else:
        eleves = Eleve.objects.all()

    if ecole_id: eleves = eleves.filter(ecole_id=ecole_id)
    if niveau_id: eleves = eleves.filter(niveau_id=niveau_id)
    if classe_id: eleves = eleves.filter(classe_id=classe_id)
    if annee_id: eleves = eleves.filter(annee_scolaire_id=annee_id)

    bulletins = []
    for eleve in eleves:
        resultat_annuel = ResultatAnnuel.objects.filter(eleve=eleve, annee_scolaire_id=annee_id).first()
        if resultat_annuel:
            bulletins.append({
                'eleve': eleve, 'resultat_annuel': resultat_annuel,
                'moyenne': resultat_annuel.moyenne_generale,
                'pourcentage': resultat_annuel.pourcentage_general,
            })
        else:
            bulletins.append({'eleve': eleve, 'resultat_annuel': None, 'moyenne': 0, 'pourcentage': 0})

    if user.est_enseignant():
        ecoles = Ecole.objects.filter(id=user.ecole_affectation.id) if user.ecole_affectation else Ecole.objects.none()
        niveaux = Niveau.objects.filter(ecole=user.ecole_affectation, est_reference=False) if user.ecole_affectation else Niveau.objects.none()
        classes = Classe.objects.filter(id=user.classe_affectation.id) if user.classe_affectation else Classe.objects.none()
    elif user.est_inspecteur():
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
        'bulletins': bulletins, 'ecoles': ecoles, 'niveaux': niveaux, 'classes': classes,
        'annees': AnneeScolaire.objects.all(),
        'selected_ecole': ecole_id, 'selected_niveau': niveau_id,
        'selected_classe': classe_id, 'selected_annee': annee_id,
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

    if user.est_parent() or user.est_ministre() or user.est_agent():
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
    elif user.est_inspecteur():
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
    else:
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
                    cours_id=cours_id, annee_scolaire=annee, evaluation_config=eval_config
                ).values_list('eleve_id', flat=True).distinct()
            except EvaluationConfig.DoesNotExist:
                messages.error(request, 'Évaluation invalide.')
                return redirect('ecoles:eleves_sans_notes')
        else:
            eleves_avec_notes = EvaluationResultat.objects.filter(
                cours_id=cours_id, annee_scolaire=annee
            ).values_list('eleve_id', flat=True).distinct()

        eleves_sans = eleves.exclude(id__in=eleves_avec_notes)

        paginator = Paginator(eleves_sans, 20)
        page = request.GET.get('page')
        eleves_sans = paginator.get_page(page)

        context = {
            'eleves': eleves_sans, 'cours': cours, 'annee': annee,
            'classe_selected': classe_id, 'classes': classes,
            'cours_list': cours_qs,
            'annees': AnneeScolaire.objects.all().order_by('-annee'),
            'selected_cours': cours_id, 'selected_annee': annee_id,
            'selected_evaluation': evaluation_id,
            'eval_configs': eval_configs, 'has_filter': True,
        }
    else:
        context = {
            'eleves': None, 'classes': classes, 'cours_list': cours_qs,
            'annees': AnneeScolaire.objects.all().order_by('-annee'),
            'selected_cours': cours_id, 'selected_annee': annee_id,
            'selected_evaluation': None,
            'eval_configs': eval_configs, 'has_filter': False,
        }

    return render(request, 'ecoles/eleves_sans_notes.html', context)


# ===================== CORBEILLE =====================
def trash_list(request):
    if not request.user.is_authenticated or not request.user.est_administrateur():
        messages.error(request, 'Accès non autorisé.')
        return redirect('ecoles:dashboard')
    items = []
    models = [Ecole, Niveau, Classe, Cours, Eleve, Province]
    for model in models:
        if hasattr(model, 'all_objects'):
            qs = model.all_objects.filter(deleted_at__isnull=False)
            for obj in qs:
                items.append({
                    'id': obj.id, 'name': str(obj),
                    'model': model.__name__, 'deleted_at': obj.deleted_at,
                })
    items.sort(key=lambda x: x['deleted_at'], reverse=True)
    return render(request, 'ecoles/trash_list.html', {'trash_items': items, 'title': 'Corbeille'})


def restore_item(request, model_name, pk):
    if not request.user.is_authenticated or not request.user.est_administrateur():
        messages.error(request, 'Accès non autorisé.')
        return redirect('ecoles:dashboard')
    model_map = {
        'Ecole': Ecole, 'Niveau': Niveau, 'Classe': Classe,
        'Cours': Cours, 'Eleve': Eleve, 'Province': Province,
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
    if not request.user.is_authenticated or not request.user.est_administrateur():
        messages.error(request, 'Accès non autorisé.')
        return redirect('ecoles:dashboard')
    model_map = {
        'Ecole': Ecole, 'Niveau': Niveau, 'Classe': Classe,
        'Cours': Cours, 'Eleve': Eleve, 'Province': Province,
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
    models = [Ecole, Niveau, Classe, Cours, Eleve, Province]
    deleted_count = 0
    for model in models:
        if hasattr(model, 'all_objects'):
            count = model.all_objects.filter(deleted_at__isnull=False).count()
            model.all_objects.filter(deleted_at__isnull=False).delete()
            deleted_count += count
    messages.success(request, f'La corbeille a été vidée ({deleted_count} élément(s)).')
    return redirect('ecoles:trash_list')


# ===================== API =====================
@login_required
def api_get_niveaux(request):
    from accounts.models import Utilisateur

    ecole_id = request.GET.get('ecole_id')
    if not ecole_id:
        return JsonResponse([], safe=False)

    niveaux_pris = Utilisateur.objects.exclude(
        niveau_affectation__isnull=True
    ).values_list('niveau_affectation_id', flat=True)

    current_user_id = request.GET.get('current_user_id')
    if current_user_id:
        try:
            current_user_id_int = int(current_user_id)
            niveaux_pris = Utilisateur.objects.exclude(
                niveau_affectation__isnull=True
            ).exclude(pk=current_user_id_int).values_list('niveau_affectation_id', flat=True)
        except (ValueError, TypeError):
            pass

    niveaux = Niveau.objects.filter(
        ecole_id=ecole_id,
        est_reference=False,
    ).exclude(id__in=niveaux_pris).select_related('section').order_by('nom')

    data = []
    for niveau in niveaux:
        label = niveau.nom or NOM_NIVEAU_PAR_DEFAUT
        if niveau.section:
            label += f" - {niveau.section.nom or NOM_SECTION_PAR_DEFAUT}"
        data.append({'id': niveau.id, 'nom': label})
    return JsonResponse(data, safe=False)


@login_required
def api_get_classes(request):
    from accounts.models import Utilisateur

    ecole_id = request.GET.get('ecole_id')
    niveau_id = request.GET.get('niveau_id')

    classes_prises = Utilisateur.objects.exclude(
        classe_affectation__isnull=True
    ).values_list('classe_affectation_id', flat=True)

    current_user_id = request.GET.get('current_user_id')
    if current_user_id:
        try:
            current_user_id_int = int(current_user_id)
            classes_prises = Utilisateur.objects.exclude(
                classe_affectation__isnull=True
            ).exclude(pk=current_user_id_int).values_list('classe_affectation_id', flat=True)
        except (ValueError, TypeError):
            pass

    queryset = Classe.objects.filter(est_reference=False).select_related('niveau', 'niveau__section')
    if ecole_id:
        queryset = queryset.filter(ecole_id=ecole_id)
    if niveau_id:
        queryset = queryset.filter(niveau_id=niveau_id)

    queryset = queryset.exclude(id__in=classes_prises).order_by('niveau__nom', 'nom')

    data = []
    for classe in queryset:
        data.append({'id': classe.id, 'nom': _label_classe_complet(classe)})

    return JsonResponse(data, safe=False)


@login_required
def api_get_classes_by_niveau(request):
    from accounts.models import Utilisateur

    niveau_id = request.GET.get('niveau_id')
    ecole_id = request.GET.get('ecole_id')
    reference = request.GET.get('reference') == '1'

    if not niveau_id:
        return JsonResponse([], safe=False)

    try:
        queryset = Classe.objects.filter(niveau_id=niveau_id).select_related(
            'niveau', 'niveau__section', 'ecole'
        )

        if reference:
            queryset = queryset.filter(
                est_reference=True,
                ecole__isnull=True,
            )
        else:
            queryset = queryset.filter(est_reference=False)
            if ecole_id:
                queryset = queryset.filter(ecole_id=ecole_id)

            classes_prises = Utilisateur.objects.exclude(
                classe_affectation__isnull=True
            ).values_list('classe_affectation_id', flat=True)

            current_user_id = request.GET.get('current_user_id')
            if current_user_id:
                try:
                    current_user_id_int = int(current_user_id)
                    classes_prises = Utilisateur.objects.exclude(
                        classe_affectation__isnull=True
                    ).exclude(pk=current_user_id_int).values_list(
                        'classe_affectation_id', flat=True
                    )
                except (ValueError, TypeError):
                    pass

            queryset = queryset.exclude(id__in=classes_prises)

        queryset = queryset.order_by('nom')

        data = []
        for classe in queryset:
            data.append({'id': classe.id, 'nom': _label_classe_complet(classe)})

        return JsonResponse(data, safe=False)

    except Exception as e:
        logger.exception("Erreur api_get_classes_by_niveau")
        return JsonResponse([], safe=False)


@login_required
def api_get_eleves(request):
    user = request.user
    if user.est_agent() or user.est_parent() or user.est_ministre():
        return JsonResponse([], safe=False)

    ecole_id = request.GET.get('ecole_id')
    niveau_id = request.GET.get('niveau_id')
    classe_id = request.GET.get('classe_id')
    queryset = Eleve.objects.all()

    if user.est_enseignant() and user.classe_affectation:
        queryset = queryset.filter(classe=user.classe_affectation)
    elif user.est_inspecteur() and user.ecole_affectation:
        queryset = queryset.filter(ecole=user.ecole_affectation)
    elif user.est_proved() and user.province_affectation:
        queryset = queryset.filter(ecole__province=user.province_affectation)

    if ecole_id: queryset = queryset.filter(ecole_id=ecole_id)
    if niveau_id: queryset = queryset.filter(niveau_id=niveau_id)
    if classe_id: queryset = queryset.filter(classe_id=classe_id)
    eleves = queryset.values('id', 'nom', 'postnom', 'prenom')
    for e in eleves:
        e['nom_complet'] = f"{e['nom']} {e['postnom']} {e['prenom']}".strip()
    return JsonResponse(list(eleves), safe=False)


@login_required
def api_get_cours(request):
    user = request.user
    if user.est_agent() or user.est_parent() or user.est_ministre():
        return JsonResponse([], safe=False)

    niveau_id = request.GET.get('niveau_id')
    classe_id = request.GET.get('classe_id')
    ecole_id = request.GET.get('ecole_id')

    if not ecole_id and request.user.ecole_affectation_id:
        ecole_id = request.user.ecole_affectation_id

    queryset = Cours.objects.filter(est_reference=False)

    if niveau_id:
        queryset = queryset.filter(niveau_id=niveau_id)
    if classe_id:
        queryset = queryset.filter(classe_id=classe_id)
    if ecole_id:
        queryset = queryset.filter(ecole_id=ecole_id)

    distinct_ids = (
        queryset
        .values('nom', 'classe', 'ecole')
        .annotate(min_id=Min('id'))
        .values_list('min_id', flat=True)
    )
    cours_distincts = Cours.objects.filter(id__in=distinct_ids).order_by('nom')
    data = list(cours_distincts.values('id', 'nom'))
    return JsonResponse(data, safe=False)


# ===================== API PUBLIQUES =====================
def autocomplete_eleves(request):
    q = request.GET.get('q', '').strip()
    if len(q) < 2:
        return JsonResponse({'results': []})

    user = request.user
    if user.is_authenticated and user.est_agent():
        return JsonResponse({'results': []})

    eleves_qs = Eleve.objects.filter(
        Q(nom__icontains=q) |
        Q(postnom__icontains=q) |
        Q(prenom__icontains=q) |
        Q(matricule__icontains=q)
    )

    if user.is_authenticated:
        if user.est_enseignant():
            if user.classe_affectation:
                eleves_qs = eleves_qs.filter(classe=user.classe_affectation)
            else:
                eleves_qs = eleves_qs.none()
        elif user.est_inspecteur():
            if user.ecole_affectation:
                eleves_qs = eleves_qs.filter(ecole=user.ecole_affectation)
            else:
                eleves_qs = eleves_qs.none()
        elif user.est_proved():
            if user.province_affectation:
                eleves_qs = eleves_qs.filter(ecole__province=user.province_affectation)
            else:
                eleves_qs = eleves_qs.none()

    eleves = eleves_qs.select_related(
        'classe', 'classe__niveau', 'classe__niveau__section',
        'niveau', 'niveau__section', 'ecole'
    )[:10]

    results = []
    for eleve in eleves:
        niveau_nom = NOM_NIVEAU_PAR_DEFAUT
        niveau_id = None

        niveau_source = None
        if eleve.classe and eleve.classe.niveau:
            niveau_source = eleve.classe.niveau
        elif eleve.niveau:
            niveau_source = eleve.niveau

        if niveau_source:
            niveau_id = niveau_source.id
            base_nom = niveau_source.nom.strip() if (
                niveau_source.nom and niveau_source.nom.strip()
            ) else NOM_NIVEAU_PAR_DEFAUT

            if niveau_source.section:
                section_nom = niveau_source.section.nom.strip() if (
                    niveau_source.section.nom and niveau_source.section.nom.strip()
                ) else NOM_SECTION_PAR_DEFAUT
                niveau_nom = f"{base_nom} ({section_nom})"
            else:
                niveau_nom = base_nom

        classe_nom = '-'
        classe_id = None
        if eleve.classe:
            classe_id = eleve.classe.id
            classe_nom = _label_classe_complet(eleve.classe)

        ecole_nom = '-'
        ecole_id = None
        if eleve.ecole:
            ecole_id = eleve.ecole.id
            ecole_nom = eleve.ecole.nom or '-'

        results.append({
            'id': eleve.id,
            'nom_complet': eleve.get_nom_complet(),
            'classe': classe_nom,
            'classe_id': classe_id,
            'niveau': niveau_nom,
            'niveau_id': niveau_id,
            'ecole': ecole_nom,
            'ecole_id': ecole_id,
            'matricule': eleve.matricule or '-',
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

        nb_cycles = cycle_eval.get_nombre_cycles()
        eval_configs = cycle_eval.evaluations.filter(cycle_num__lte=nb_cycles).order_by('cycle_num', 'ordre')

        evaluations = []
        for config in eval_configs:
            try:
                resultat = EvaluationResultat.objects.get(
                    eleve=eleve, cours=cours,
                    annee_scolaire=annee, evaluation_config=config
                )
                evaluations.append({
                    'cycle': config.cycle_num, 'periode': config.periode_num,
                    'type': config.type,
                    'points_obtenus': float(resultat.points_obtenus),
                    'points_max': config.points_max
                })
            except EvaluationResultat.DoesNotExist:
                pass

        if evaluations:
            resultats_par_cours[cours.id] = {
                'cours_nom': cours.nom, 'evaluations': evaluations
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
            'prenom': eleve.prenom, 'nom': eleve.nom
        },
        'resultats_par_cours': resultats_par_cours,
        'resultat_annuel': annuel_data
    }
    return JsonResponse(response_data)