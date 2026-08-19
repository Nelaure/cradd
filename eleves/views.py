from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.utils import timezone
from .models import Eleve, Bulletin, ParcoursEleve, MasquageEvaluation, MasquageColonne
from .forms import EleveForm, BulletinForm
from ecoles.models import Ecole, Niveau, Classe, AnneeScolaire, Cours, CycleEvaluation, EvaluationConfig
from ecoles.models import EvaluationResultat, ResultatCycle, ResultatAnnuel

# ===================== LISTE DES ÉLÈVES =====================
@login_required
def eleve_list(request):
    user = request.user
    if user.est_parent():
        eleves_qs = user.eleves_associes.all()
    elif user.est_enseignant():
        if user.classe_affectation:
            eleves_qs = Eleve.objects.filter(classe=user.classe_affectation)
        else:
            eleves_qs = Eleve.objects.none()
    elif user.est_agent() or user.est_inspecteur():
        eleves_qs = Eleve.objects.filter(ecole=user.ecole_affectation) if user.ecole_affectation else Eleve.objects.none()
    elif user.est_proved():
        if user.province_affectation:
            ecoles = Ecole.objects.filter(province=user.province_affectation)
            eleves_qs = Eleve.objects.filter(ecole__in=ecoles)
        else:
            eleves_qs = Eleve.objects.none()
    else:
        eleves_qs = Eleve.objects.all()

    ecole_id = request.GET.get('ecole')
    niveau_id = request.GET.get('niveau')
    classe_id = request.GET.get('classe')
    annee_id = request.GET.get('annee')
    if ecole_id:
        eleves_qs = eleves_qs.filter(ecole_id=ecole_id)
    if niveau_id:
        eleves_qs = eleves_qs.filter(niveau_id=niveau_id)
    if classe_id:
        eleves_qs = eleves_qs.filter(classe_id=classe_id)
    if annee_id:
        eleves_qs = eleves_qs.filter(annee_scolaire_id=annee_id)

    paginator = Paginator(eleves_qs.order_by('nom', 'prenom'), 20)
    page = request.GET.get('page')
    eleves_page = paginator.get_page(page)

    if user.est_parent():
        ecoles = Ecole.objects.filter(eleves__in=eleves_qs).distinct()
        niveaux = Niveau.objects.filter(eleves__in=eleves_qs).distinct()
        classes = Classe.objects.filter(eleves__in=eleves_qs).distinct()
    elif user.est_enseignant():
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
        ecoles = Ecole.objects.filter(eleves__in=eleves_qs).distinct()
        niveaux = Niveau.objects.filter(eleves__in=eleves_qs).distinct()
        classes = Classe.objects.filter(eleves__in=eleves_qs).distinct()

    context = {
        'eleves': eleves_page,
        'ecoles': ecoles,
        'niveaux': niveaux,
        'classes': classes,
        'annees': AnneeScolaire.objects.all(),
        'selected_ecole': ecole_id,
        'selected_niveau': niveau_id,
        'selected_classe': classe_id,
        'selected_annee': annee_id,
    }
    return render(request, 'eleves/eleve_list.html', context)


# ===================== CRÉATION D'ÉLÈVE =====================
@login_required
def eleve_create(request):
    user = request.user
    if user.est_parent():
        messages.error(request, 'Vous n\'avez pas les droits pour créer un élève.')
        return redirect('eleves:eleve_list')
    if request.method == 'POST':
        form = EleveForm(request.POST, request.FILES, user=user)
        if form.is_valid():
            eleve = form.save(commit=False)
            if user.est_enseignant():
                eleve.ecole = user.ecole_affectation
                eleve.classe = user.classe_affectation
                eleve.niveau = user.niveau_affectation
            elif user.est_agent() or user.est_inspecteur():
                eleve.ecole = user.ecole_affectation
            elif user.est_proved():
                pass
            eleve.save()
            ParcoursEleve.objects.create(
                eleve=eleve,
                annee_scolaire=eleve.annee_scolaire,
                ecole=eleve.ecole,
                niveau=eleve.niveau,
                classe=eleve.classe,
                date_debut=timezone.now().date(),
                est_actuel=True
            )
            messages.success(request, f'Élève {eleve.get_nom_complet()} créé avec succès.')
            return redirect('eleves:eleve_list')
    else:
        form = EleveForm(user=user)
        if user.est_enseignant() and user.classe_affectation:
            form.fields['classe'].initial = user.classe_affectation.id
            form.fields['niveau'].initial = user.niveau_affectation.id if user.niveau_affectation else None
            form.fields['ecole'].initial = user.ecole_affectation.id if user.ecole_affectation else None
    return render(request, 'eleves/eleve_form.html', {'form': form, 'title': 'Créer un élève'})


# ===================== MODIFICATION D'ÉLÈVE =====================
@login_required
def eleve_edit(request, pk):
    eleve = get_object_or_404(Eleve, pk=pk)
    user = request.user
    if user.est_parent():
        messages.error(request, 'Accès non autorisé.')
        return redirect('eleves:eleve_list')
    if user.est_enseignant():
        if eleve.classe != user.classe_affectation:
            messages.error(request, 'Accès non autorisé.')
            return redirect('ecoles:dashboard')
    elif user.est_agent() and eleve.ecole != user.ecole_affectation:
        messages.error(request, 'Accès non autorisé.')
        return redirect('ecoles:dashboard')
    elif user.est_proved() and (eleve.ecole.province != user.province_affectation):
        messages.error(request, 'Accès non autorisé.')
        return redirect('ecoles:dashboard')
    elif not (user.est_administrateur() or user.est_inspecteur()):
        messages.error(request, 'Accès non autorisé.')
        return redirect('ecoles:dashboard')

    if request.method == 'POST':
        form = EleveForm(request.POST, request.FILES, instance=eleve, user=user)
        if form.is_valid():
            eleve = form.save(commit=False)
            if user.est_enseignant():
                eleve.ecole = user.ecole_affectation
                eleve.classe = user.classe_affectation
                eleve.niveau = user.niveau_affectation
            elif user.est_agent() or user.est_inspecteur():
                eleve.ecole = user.ecole_affectation
            elif user.est_proved():
                pass
            eleve.save()
            parcours, created = ParcoursEleve.objects.get_or_create(
                eleve=eleve,
                annee_scolaire=eleve.annee_scolaire,
                defaults={
                    'ecole': eleve.ecole,
                    'niveau': eleve.niveau,
                    'classe': eleve.classe,
                    'date_debut': timezone.now().date(),
                    'est_actuel': True
                }
            )
            if not created:
                parcours.ecole = eleve.ecole
                parcours.niveau = eleve.niveau
                parcours.classe = eleve.classe
                parcours.save()
            messages.success(request, 'Élève modifié avec succès.')
            return redirect('eleves:eleve_list')
    else:
        form = EleveForm(instance=eleve, user=user)
        if user.est_enseignant():
            form.fields['ecole'].disabled = True
            form.fields['niveau'].disabled = True
            form.fields['classe'].disabled = True
        elif user.est_agent() or user.est_inspecteur():
            form.fields['ecole'].disabled = True
    return render(request, 'eleves/eleve_form.html', {'form': form, 'title': 'Modifier un élève'})


# ===================== DÉTAIL D'ÉLÈVE =====================
@login_required
def eleve_detail(request, pk):
    eleve = get_object_or_404(Eleve, pk=pk)
    user = request.user

    # Vérifications d'accès
    if user.est_parent():
        if eleve not in user.eleves_associes.all():
            messages.error(request, 'Accès non autorisé à cet élève.')
            return redirect('eleves:eleve_list')
    elif user.est_enseignant():
        if eleve.classe != user.classe_affectation:
            messages.error(request, 'Accès non autorisé.')
            return redirect('eleves:eleve_list')
    elif user.est_agent() and eleve.ecole != user.ecole_affectation:
        messages.error(request, 'Accès non autorisé.')
        return redirect('eleves:eleve_list')
    elif user.est_proved() and (eleve.ecole.province != user.province_affectation):
        messages.error(request, 'Accès non autorisé.')
        return redirect('eleves:eleve_list')

    # Récupérer tous les parcours
    parcours_list = ParcoursEleve.objects.filter(eleve=eleve).select_related('annee_scolaire', 'ecole', 'niveau', 'classe')
    annees_disponibles = [p.annee_scolaire for p in parcours_list]
    if not annees_disponibles:
        annee_actuelle = AnneeScolaire.objects.filter(est_actuelle=True).first()
        annees_disponibles = [annee_actuelle] if annee_actuelle else [eleve.annee_scolaire] if eleve.annee_scolaire else []

    user_is_parent = user.est_parent()
    resultats_par_annee = {}

    for annee in annees_disponibles:
        parcours = parcours_list.filter(annee_scolaire=annee).first()
        cours_list = []
        if parcours and parcours.classe:
            cours_list = parcours.classe.cours.all()
        elif annee == eleve.annee_scolaire and eleve.classe:
            cours_list = eleve.classe.cours.all()

        resultats_par_cours = {}

        for cours in cours_list:
            try:
                cycle_eval = cours.cycle_evaluation
            except CycleEvaluation.DoesNotExist:
                cycle_eval = CycleEvaluation.objects.create(cours=cours, type_cycle='trimestre')
                cycle_eval.creer_evaluations_par_defaut()

            eval_configs = cycle_eval.evaluations.all().order_by('cycle_num', 'ordre')
            evaluations = []
            masques_par_cycle = {}  # pour le bouton de visibilité du cycle entier
            masques_colonnes = {}    # pour les boutons de colonne (période/examen)

            # Récupérer les masquages de colonnes pour ce cours/année/élève
            for mc in MasquageColonne.objects.filter(
                eleve=eleve,
                annee_scolaire=annee,
                cours=cours
            ):
                key = f"{mc.cycle_num}_{mc.type}_{mc.periode_num if mc.periode_num is not None else 'None'}"
                masques_colonnes[key] = mc.masque

            for config in eval_configs:
                try:
                    resultat = EvaluationResultat.objects.get(
                        eleve=eleve,
                        cours=cours,
                        annee_scolaire=annee,
                        evaluation_config=config
                    )
                    masquage_obj = MasquageEvaluation.objects.filter(
                        eleve=eleve,
                        annee_scolaire=annee,
                        evaluation_config=config
                    ).first()
                    masque_eval = masquage_obj.masque if masquage_obj else False
                except EvaluationResultat.DoesNotExist:
                    resultat = None
                    masquage_obj = MasquageEvaluation.objects.filter(
                        eleve=eleve,
                        annee_scolaire=annee,
                        evaluation_config=config
                    ).first()
                    masque_eval = masquage_obj.masque if masquage_obj else False

                cycle = config.cycle_num
                points_max = config.points_max

                # Mettre à jour masques_par_cycle pour le bouton (enseignant)
                if cycle not in masques_par_cycle:
                    masques_par_cycle[cycle] = masque_eval
                else:
                    if masque_eval:
                        masques_par_cycle[cycle] = True

                # Vérifier le masquage de colonne
                colonne_key = f"{cycle}_{config.type}_{config.periode_num if config.periode_num is not None else 'None'}"
                colonne_masque = masques_colonnes.get(colonne_key, False)

                # Pour le parent : on masque la colonne si colonne_masque est True
                if user_is_parent and colonne_masque:
                    est_masque_pour_parent = True
                    points_obtenus = None
                else:
                    est_masque_pour_parent = False
                    points_obtenus = float(resultat.points_obtenus) if resultat else None

                evaluations.append({
                    'config_id': config.id,
                    'cycle': cycle,
                    'periode': config.periode_num,
                    'type': config.type,
                    'points_obtenus': points_obtenus,
                    'points_max': points_max,
                    'masque': masque_eval,
                    'est_masque_pour_parent': est_masque_pour_parent,
                    'colonne_masque': colonne_masque,
                })

            if evaluations:
                resultats_par_cours[cours.id] = {
                    'cours_nom': cours.nom,
                    'evaluations': evaluations,
                    'masques_par_cycle': masques_par_cycle,
                    'masques_colonnes': masques_colonnes,
                    'totaux_cycle': {}
                }

        # Construction des masques de colonnes globaux pour cette année
        masques_colonnes_globaux = {}
        for cours_data in resultats_par_cours.values():
            for key, value in cours_data.get('masques_colonnes', {}).items():
                if key not in masques_colonnes_globaux:
                    masques_colonnes_globaux[key] = value
                else:
                    if value:
                        masques_colonnes_globaux[key] = True

        # Calcul des cycles et périodes
        cycles_set = set()
        periodes_map = {}
        for cours_data in resultats_par_cours.values():
            for eval in cours_data['evaluations']:
                cycle = eval['cycle']
                cycles_set.add(cycle)
                if cycle not in periodes_map:
                    periodes_map[cycle] = set()
                if eval['type'] == 'periode' and eval['periode'] is not None:
                    periodes_map[cycle].add(eval['periode'])

        cycles_info = []
        for cycle_num in sorted(cycles_set):
            periodes = sorted(periodes_map.get(cycle_num, []))

            # Vérifier si le cycle est entièrement masqué pour le parent (via masquage individuel)
            cycle_masque_parent = False
            if user_is_parent:
                all_masque = True
                for cours_data in resultats_par_cours.values():
                    for eval in cours_data['evaluations']:
                        if eval['cycle'] == cycle_num and not eval['est_masque_pour_parent']:
                            all_masque = False
                            break
                    if not all_masque:
                        break
                cycle_masque_parent = all_masque

            # Ajouter les totaux par matière pour ce cycle
            for cours_id, cours_data in resultats_par_cours.items():
                total_obtenu = 0
                total_possible = 0
                for eval in cours_data['evaluations']:
                    if eval['cycle'] == cycle_num:
                        total_possible += eval['points_max']
                        if not eval['est_masque_pour_parent'] and eval['points_obtenus'] is not None:
                            total_obtenu += eval['points_obtenus']
                if user_is_parent and cycle_masque_parent:
                    cours_data['totaux_cycle'] = {
                        'total_obtenu': None,
                        'total_possible': None,
                        'pourcentage': None,
                        'masque': True
                    }
                else:
                    cours_data['totaux_cycle'] = {
                        'total_obtenu': total_obtenu,
                        'total_possible': total_possible,
                        'pourcentage': (total_obtenu / total_possible * 100) if total_possible > 0 else 0,
                        'masque': False
                    }

            # Totaux globaux du cycle, avec masquage par colonne
            totals = []
            # Pour chaque période
            for periode in periodes:
                total_obtenu = 0
                total_possible = 0
                colonne_masquee = False
                for cours_data in resultats_par_cours.values():
                    for eval in cours_data['evaluations']:
                        if eval['cycle'] == cycle_num and eval['type'] == 'periode' and eval['periode'] == periode:
                            total_possible += eval['points_max']
                            if eval['colonne_masque']:
                                colonne_masquee = True
                            if not eval['est_masque_pour_parent'] and eval['points_obtenus'] is not None:
                                total_obtenu += eval['points_obtenus']
                if user_is_parent and colonne_masquee:
                    totals.append({
                        'type': 'periode',
                        'periode': periode,
                        'total_obtenu': None,
                        'total_possible': None,
                        'pourcentage': None,
                        'masque': True,
                        'colonne_masquee': True
                    })
                else:
                    pourcentage = (total_obtenu / total_possible * 100) if total_possible > 0 else 0
                    totals.append({
                        'type': 'periode',
                        'periode': periode,
                        'total_obtenu': total_obtenu,
                        'total_possible': total_possible,
                        'pourcentage': pourcentage,
                        'masque': False,
                        'colonne_masquee': False
                    })

            # Examen
            total_obtenu = 0
            total_possible = 0
            colonne_masquee = False
            for cours_data in resultats_par_cours.values():
                for eval in cours_data['evaluations']:
                    if eval['cycle'] == cycle_num and eval['type'] == 'examen':
                        total_possible += eval['points_max']
                        if eval['colonne_masque']:
                            colonne_masquee = True
                        if not eval['est_masque_pour_parent'] and eval['points_obtenus'] is not None:
                            total_obtenu += eval['points_obtenus']
            if user_is_parent and colonne_masquee:
                totals.append({
                    'type': 'examen',
                    'periode': None,
                    'total_obtenu': None,
                    'total_possible': None,
                    'pourcentage': None,
                    'masque': True,
                    'colonne_masquee': True
                })
            else:
                pourcentage = (total_obtenu / total_possible * 100) if total_possible > 0 else 0
                totals.append({
                    'type': 'examen',
                    'periode': None,
                    'total_obtenu': total_obtenu,
                    'total_possible': total_possible,
                    'pourcentage': pourcentage,
                    'masque': False,
                    'colonne_masquee': False
                })

            cycles_info.append({
                'cycle_num': cycle_num,
                'periodes': periodes,
                'totals': totals,
                'masque_parent': user_is_parent and cycle_masque_parent
            })

        # Résultat annuel
        resultat_annuel = ResultatAnnuel.objects.filter(eleve=eleve, annee_scolaire=annee).first()
        annuel_data = {
            'pourcentage_general': float(resultat_annuel.pourcentage_general) if resultat_annuel else None,
            'moyenne_generale': float(resultat_annuel.moyenne_generale) if resultat_annuel else None
        }

        resultats_par_annee[annee.id] = {
            'annee': annee,
            'parcours': parcours,
            'resultats_par_cours': resultats_par_cours,
            'cycles_info': cycles_info,
            'annuel_data': annuel_data,
            'masques_colonnes_globaux': masques_colonnes_globaux,
        }

    bulletins = Bulletin.objects.filter(eleve=eleve).order_by('-annee_scolaire__annee')

    context = {
        'eleve': eleve,
        'bulletins': bulletins,
        'resultats_par_annee': resultats_par_annee,
        'annees_disponibles': annees_disponibles,
        'user_can_edit_visibility': user.est_enseignant() or user.est_agent() or user.est_administrateur(),
        'is_parent': user_is_parent,
    }
    return render(request, 'eleves/eleve_detail.html', context)


# ===================== BASCULE DE MASQUAGE (évaluation) =====================
@login_required
def toggle_masquage(request):
    if not request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({'success': False, 'error': 'Requête AJAX requise'}, status=400)

    eleve_id = request.GET.get('eleve_id')
    annee_id = request.GET.get('annee_id')
    cours_id = request.GET.get('cours_id')
    cycle_num = request.GET.get('cycle_num')

    if not all([eleve_id, annee_id, cours_id, cycle_num]):
        return JsonResponse({'success': False, 'error': 'Paramètres manquants'}, status=400)

    try:
        eleve = Eleve.objects.get(pk=eleve_id)
        annee = AnneeScolaire.objects.get(pk=annee_id)
        cours = Cours.objects.get(pk=cours_id)
        cycle_num = int(cycle_num)
    except (Eleve.DoesNotExist, AnneeScolaire.DoesNotExist, Cours.DoesNotExist, ValueError):
        return JsonResponse({'success': False, 'error': 'Élément invalide'}, status=404)

    user = request.user
    if user.est_enseignant():
        if eleve.classe != user.classe_affectation:
            return JsonResponse({'success': False, 'error': 'Accès non autorisé'}, status=403)
    elif user.est_agent() and eleve.ecole != user.ecole_affectation:
        return JsonResponse({'success': False, 'error': 'Accès non autorisé'}, status=403)
    elif user.est_inspecteur() and eleve.ecole != user.ecole_affectation:
        return JsonResponse({'success': False, 'error': 'Accès non autorisé'}, status=403)
    elif user.est_proved() and (eleve.ecole.province != user.province_affectation):
        return JsonResponse({'success': False, 'error': 'Accès non autorisé'}, status=403)
    elif not (user.est_administrateur() or user.est_enseignant() or user.est_agent()):
        return JsonResponse({'success': False, 'error': 'Accès non autorisé'}, status=403)

    cycle_eval = CycleEvaluation.objects.filter(cours=cours).first()
    if not cycle_eval:
        return JsonResponse({'success': False, 'error': 'Aucune évaluation configurée pour ce cours'}, status=404)

    configs = cycle_eval.evaluations.filter(cycle_num=cycle_num)
    if not configs.exists():
        return JsonResponse({'success': False, 'error': 'Aucune évaluation trouvée pour ce cycle'}, status=404)

    modified = 0
    new_status = None
    for config in configs:
        masquage, created = MasquageEvaluation.objects.get_or_create(
            eleve=eleve,
            annee_scolaire=annee,
            evaluation_config=config,
            defaults={'masque': True}
        )
        if not created:
            masquage.masque = not masquage.masque
            masquage.save()
        modified += 1
        new_status = masquage.masque

    return JsonResponse({
        'success': True,
        'masque': new_status,
        'modified_count': modified,
        'message': f'{modified} évaluation(s) mise(s) à jour.'
    })


# ===================== BASCULE DE MASQUAGE DE COLONNE =====================
@login_required
def toggle_colonne_masquage(request):
    if not request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({'success': False, 'error': 'Requête AJAX requise'}, status=400)

    eleve_id = request.GET.get('eleve_id')
    annee_id = request.GET.get('annee_id')
    cycle_num = request.GET.get('cycle_num')
    type_col = request.GET.get('type')  # 'periode' ou 'examen'
    periode_num = request.GET.get('periode_num')  # peut être 'None'

    if not all([eleve_id, annee_id, cycle_num, type_col]):
        return JsonResponse({'success': False, 'error': 'Paramètres manquants'}, status=400)

    try:
        eleve = Eleve.objects.get(pk=eleve_id)
        annee = AnneeScolaire.objects.get(pk=annee_id)
        cycle_num = int(cycle_num)
        if periode_num and periode_num != 'None':
            periode_num = int(periode_num)
        else:
            periode_num = None
    except (Eleve.DoesNotExist, AnneeScolaire.DoesNotExist, ValueError):
        return JsonResponse({'success': False, 'error': 'Élément invalide'}, status=404)

    user = request.user
    if user.est_enseignant():
        if eleve.classe != user.classe_affectation:
            return JsonResponse({'success': False, 'error': 'Accès non autorisé'}, status=403)
    elif user.est_agent() and eleve.ecole != user.ecole_affectation:
        return JsonResponse({'success': False, 'error': 'Accès non autorisé'}, status=403)
    elif user.est_inspecteur() and eleve.ecole != user.ecole_affectation:
        return JsonResponse({'success': False, 'error': 'Accès non autorisé'}, status=403)
    elif user.est_proved() and (eleve.ecole.province != user.province_affectation):
        return JsonResponse({'success': False, 'error': 'Accès non autorisé'}, status=403)
    elif not (user.est_administrateur() or user.est_enseignant() or user.est_agent()):
        return JsonResponse({'success': False, 'error': 'Accès non autorisé'}, status=403)

    # Récupérer tous les cours de l'élève pour cette année
    parcours = ParcoursEleve.objects.filter(eleve=eleve, annee_scolaire=annee).first()
    if parcours and parcours.classe:
        cours_list = parcours.classe.cours.all()
    else:
        if annee == eleve.annee_scolaire and eleve.classe:
            cours_list = eleve.classe.cours.all()
        else:
            cours_list = Cours.objects.none()

    if not cours_list:
        return JsonResponse({'success': False, 'error': 'Aucun cours trouvé pour cette année'}, status=404)

    modified = 0
    new_status = None
    for cours in cours_list:
        masquage, created = MasquageColonne.objects.get_or_create(
            eleve=eleve,
            annee_scolaire=annee,
            cours=cours,
            cycle_num=cycle_num,
            type=type_col,
            periode_num=periode_num,
            defaults={'masque': True}
        )
        if not created:
            masquage.masque = not masquage.masque
            masquage.save()
        modified += 1
        new_status = masquage.masque

    return JsonResponse({
        'success': True,
        'masque': new_status,
        'modified_count': modified,
        'message': f'{modified} cours mis à jour.'
    })


# ===================== SUPPRESSION D'ÉLÈVE =====================
@login_required
def eleve_delete(request, pk):
    eleve = get_object_or_404(Eleve, pk=pk)
    user = request.user
    if user.est_parent():
        messages.error(request, 'Accès non autorisé.')
        return redirect('eleves:eleve_list')
    if user.est_enseignant():
        if eleve.classe != user.classe_affectation:
            messages.error(request, 'Accès non autorisé.')
            return redirect('ecoles:dashboard')
    elif user.est_agent() and eleve.ecole != user.ecole_affectation:
        messages.error(request, 'Accès non autorisé.')
        return redirect('ecoles:dashboard')
    elif user.est_proved() and (eleve.ecole.province != user.province_affectation):
        messages.error(request, 'Accès non autorisé.')
        return redirect('ecoles:dashboard')
    if request.method == 'POST':
        nom = eleve.get_nom_complet()
        eleve.delete()
        messages.success(request, f'Élève {nom} supprimé avec succès.')
        return redirect('eleves:eleve_list')
    return render(request, 'eleves/eleve_confirm_delete.html', {'eleve': eleve})


# ===================== BULLETINS =====================
@login_required
def bulletin_create(request):
    user = request.user
    if request.method == 'POST':
        form = BulletinForm(request.POST, request.FILES, user=user)
        if form.is_valid():
            bulletin = form.save(commit=False)
            bulletin.upload_par = user
            if user.est_parent():
                if bulletin.eleve not in user.eleves_associes.all():
                    messages.error(request, 'Accès non autorisé à cet élève.')
                    return redirect('eleves:eleve_list')
            elif user.est_enseignant():
                if bulletin.eleve.classe != user.classe_affectation:
                    messages.error(request, 'Accès non autorisé à cet élève.')
                    return redirect('eleves:eleve_list')
            elif user.est_agent() and bulletin.eleve.ecole != user.ecole_affectation:
                messages.error(request, 'Accès non autorisé à cet élève.')
                return redirect('eleves:eleve_list')
            elif user.est_proved() and (bulletin.eleve.ecole.province != user.province_affectation):
                messages.error(request, 'Accès non autorisé à cet élève.')
                return redirect('eleves:eleve_list')
            bulletin.save()
            messages.success(request, 'Bulletin téléchargé avec succès.')
            return redirect('eleves:eleve_detail', pk=bulletin.eleve.pk)
    else:
        eleve_id = request.GET.get('eleve')
        form = BulletinForm(initial={'eleve': eleve_id} if eleve_id else None, user=user)
        if user.est_parent():
            form.fields['eleve'].queryset = user.eleves_associes.all()
        elif user.est_enseignant() and user.classe_affectation:
            form.fields['eleve'].queryset = Eleve.objects.filter(classe=user.classe_affectation)
        elif user.est_agent() and user.ecole_affectation:
            form.fields['eleve'].queryset = Eleve.objects.filter(ecole=user.ecole_affectation)
        elif user.est_proved() and user.province_affectation:
            ecoles = Ecole.objects.filter(province=user.province_affectation)
            form.fields['eleve'].queryset = Eleve.objects.filter(ecole__in=ecoles)
    return render(request, 'eleves/bulletin_form.html', {'form': form, 'title': 'Télécharger un bulletin'})


@login_required
def bulletin_delete(request, pk):
    bulletin = get_object_or_404(Bulletin, pk=pk)
    eleve_id = bulletin.eleve.id
    user = request.user
    if user.est_parent():
        if bulletin.eleve not in user.eleves_associes.all():
            messages.error(request, 'Accès non autorisé.')
            return redirect('eleves:eleve_list')
    elif user.est_enseignant():
        if bulletin.eleve.classe != user.classe_affectation:
            messages.error(request, 'Accès non autorisé.')
            return redirect('ecoles:dashboard')
    elif user.est_agent() and bulletin.eleve.ecole != user.ecole_affectation:
        messages.error(request, 'Accès non autorisé.')
        return redirect('ecoles:dashboard')
    elif user.est_proved() and (bulletin.eleve.ecole.province != user.province_affectation):
        messages.error(request, 'Accès non autorisé.')
        return redirect('ecoles:dashboard')
    if request.method == 'POST':
        bulletin.delete()
        messages.success(request, 'Bulletin supprimé avec succès.')
    return redirect('eleves:eleve_detail', pk=eleve_id)