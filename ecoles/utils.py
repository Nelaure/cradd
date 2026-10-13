from decimal import Decimal
from django.db.models import Sum, Avg, Q
from django.utils import timezone


def recalculer_resultats_eleve(eleve, annee_scolaire):
    """Recalcule tous les ResultatCycle puis le ResultatAnnuel d'un élève."""
    from ecoles.models import (
        Cours, CycleEvaluation, EvaluationConfig,
        EvaluationResultat, ResultatCycle, ResultatAnnuel
    )

    cours_qs = Cours.objects.filter(classe=eleve.classe, est_reference=False)

    for cours in cours_qs:
        try:
            cycle_eval = cours.cycle_evaluation
        except CycleEvaluation.DoesNotExist:
            cycle_eval = CycleEvaluation.objects.create(cours=cours)
            cycle_eval.creer_evaluations_par_defaut()

        nb_cycles = cycle_eval.get_nombre_cycles()

        for cycle_num in range(1, nb_cycles + 1):
            configs = cycle_eval.evaluations.filter(cycle_num=cycle_num)
            resultats = EvaluationResultat.objects.filter(
                eleve=eleve,
                cours=cours,
                annee_scolaire=annee_scolaire,
                evaluation_config__in=configs
            )

            total_obtenus = resultats.aggregate(t=Sum('points_obtenus'))['t'] or Decimal('0.00')
            total_possibles = sum(c.points_max for c in configs)

            if total_possibles > 0:
                pourcentage = (total_obtenus / total_possibles) * 100
                moyenne = (total_obtenus / total_possibles) * 20
            else:
                pourcentage = Decimal('0.00')
                moyenne = Decimal('0.00')

            ResultatCycle.objects.update_or_create(
                eleve=eleve,
                cours=cours,
                annee_scolaire=annee_scolaire,
                cycle_num=cycle_num,
                defaults={
                    'total_points_obtenus': total_obtenus,
                    'total_points_possibles': total_possibles,
                    'pourcentage': pourcentage,
                    'moyenne_sur_20': moyenne,
                }
            )

    resultat_annuel, _ = ResultatAnnuel.objects.get_or_create(
        eleve=eleve,
        annee_scolaire=annee_scolaire
    )
    resultat_annuel.recalculer()
    return resultat_annuel


def trash_count(request):
    """Context processor : retourne le nombre d'éléments en corbeille."""
    try:
        from ecoles.models import Ecole, Niveau, Classe, Domaine, Cours, Province
        from eleves.models import Eleve

        count = 0
        for model in [Ecole, Niveau, Classe, Domaine, Cours, Province, Eleve]:
            if hasattr(model, 'all_objects'):
                count += model.all_objects.filter(deleted_at__isnull=False).count()

        return {'trash_count': count}
    except Exception:
        return {'trash_count': 0}


def get_annee_actuelle():
    """Retourne l'année scolaire actuelle ou la plus récente."""
    from ecoles.models import AnneeScolaire
    annee = AnneeScolaire.objects.filter(est_actuelle=True).first()
    if not annee:
        annee = AnneeScolaire.objects.order_by('-annee').first()
    return annee


def calculer_taux_reussite(queryset_resultats, seuil=10):
    """Calcule le taux de réussite (%) à partir d'un queryset de ResultatAnnuel."""
    total = queryset_resultats.count()
    if total == 0:
        return 0
    reussis = queryset_resultats.filter(moyenne_generale__gte=seuil).count()
    return round((reussis / total) * 100, 1)


def calculer_moyenne_generale(queryset_resultats):
    """Calcule la moyenne générale à partir d'un queryset de ResultatAnnuel."""
    avg = queryset_resultats.aggregate(avg=Avg('moyenne_generale'))['avg']
    return round(float(avg), 2) if avg is not None else 0


# ===================== SYNCHRONISATION PAR COURS DE RÉFÉRENCE =====================

def synchroniser_cours_ref_vers_instances(cours_ref, logger=None):
    """
    Synchronise UN cours de référence vers toutes ses instances d'école.

    Cherche les cours d'instance par :
      1. `reference_source=cours_ref` (prioritaire)
      2. Fallback : même nom + même domaine + classe d'instance correspondante

    Crée les cours d'instance manquants.
    Met à jour nom, coefficient, description, cycle d'évaluation.

    Retourne un rapport compatible avec `_stocker_rapport_sync`.
    """
    from ecoles.models import (
        Classe, Cours, Domaine, CycleEvaluation, EvaluationConfig,
        EvaluationResultat
    )

    def log(msg):
        if logger:
            logger.info(f"[SYNC COURS] {msg}")

    if not cours_ref.est_reference or cours_ref.ecole is not None:
        log(f"⛔ '{cours_ref}' n'est pas un cours de référence valide.")
        return None

    if not cours_ref.classe or not cours_ref.classe.est_reference:
        log(f"⛔ Le cours '{cours_ref}' n'a pas de classe de référence.")
        return None

    classe_ref = cours_ref.classe
    niveau_ref = classe_ref.niveau

    log(f"🔍 Synchronisation du cours '{cours_ref.nom}' (classe réf: '{classe_ref.nom}')")

    # ---- Trouver les instances de la classe de référence ----
    instances_classe = Classe.objects.filter(
        est_reference=False,
        ecole__isnull=False,
    ).filter(
        Q(reference_source=classe_ref) |
        Q(reference_source__isnull=True,
          nom=classe_ref.nom,
          niveau__nom=niveau_ref.nom,
          niveau__section=niveau_ref.section)
    ).select_related('ecole', 'niveau')

    log(f"📊 {instances_classe.count()} instance(s) de classe trouvée(s)")

    rapport = {
        'success': True,
        'classe_ref': str(classe_ref),
        'niveau_ref': str(niveau_ref),
        'cours_ref': str(cours_ref),
        'instances_traitees': 0,
        'cours_ajoutes': 0,
        'cours_modifies': 0,
        'evaluations_ajoutees': 0,
        'evaluations_modifiees': 0,
        'evaluations_supprimees': 0,
        'evaluations_bloquees': 0,
        'doublons_nettoyes': 0,
        'details_ecoles': [],
        'erreurs': [],
    }

    if not instances_classe.exists():
        rapport['message'] = (
            f"Aucune instance de classe trouvée pour '{classe_ref.nom}'."
        )
        log("⚠️ Aucune instance de classe. Fin.")
        return rapport

    # ---- Cycle du cours de référence ----
    cycle_ref, _ = CycleEvaluation.objects.get_or_create(cours=cours_ref)
    if not cycle_ref.evaluations.exists():
        cycle_ref.creer_evaluations_par_defaut()

    configs_ref = {
        (c.cycle_num, c.periode_num, c.type): c
        for c in cycle_ref.evaluations.all()
    }

    # ---- Traiter chaque instance de classe ----
    for classe_inst in instances_classe:
        ecole = classe_inst.ecole
        niveau_inst = classe_inst.niveau

        details = {
            'ecole': ecole.nom if ecole else '-',
            'classe_instance': str(classe_inst),
            'classes_traitees': 1,
            'classes_ajoutees': 0,
            'classes_modifiees': 0,
            'cours_ajoutes': 0,
            'cours_modifies': 0,
            'evaluations_ajoutees': 0,
            'evaluations_modifiees': 0,
            'evaluations_supprimees': 0,
            'erreurs': [],
        }

        # Auto-réparation : lier reference_source sur la classe
        if classe_inst.reference_source_id is None:
            classe_inst.reference_source = classe_ref
            classe_inst.save(update_fields=['reference_source'])
            log(f"🔧 reference_source lié pour la classe '{classe_inst}'")

        # Auto-réparation : lier reference_source sur le niveau
        if niveau_inst.reference_source_id is None and niveau_ref.est_reference:
            niveau_inst.reference_source = niveau_ref
            niveau_inst.save(update_fields=['reference_source'])

        rapport['instances_traitees'] += 1

        try:
            # ---- Domaine d'instance ----
            domaine_inst, _ = Domaine.objects.get_or_create(
                nom=cours_ref.domaine.nom,
                ecole=ecole,
                est_reference=False,
                defaults={'description': cours_ref.domaine.description},
            )

            # ---- Chercher un cours d'instance correspondant ----
            cours_inst = Cours.objects.filter(
                ecole=ecole,
                est_reference=False,
            ).filter(
                Q(reference_source=cours_ref) |
                Q(reference_source__isnull=True,
                  nom=cours_ref.nom,
                  classe=classe_inst,
                  domaine=domaine_inst)
            ).first()

            if cours_inst:
                # Auto-réparation
                if cours_inst.reference_source_id is None:
                    cours_inst.reference_source = cours_ref
                    cours_inst.save(update_fields=['reference_source'])

                modifie = False
                if cours_inst.nom != cours_ref.nom:
                    cours_inst.nom = cours_ref.nom
                    modifie = True
                if cours_inst.coefficient != cours_ref.coefficient:
                    cours_inst.coefficient = cours_ref.coefficient
                    modifie = True
                if cours_inst.description != cours_ref.description:
                    cours_inst.description = cours_ref.description
                    modifie = True
                if cours_inst.classe_id != classe_inst.id:
                    cours_inst.classe = classe_inst
                    modifie = True
                if cours_inst.niveau_id != niveau_inst.id:
                    cours_inst.niveau = niveau_inst
                    modifie = True
                if cours_inst.domaine_id != domaine_inst.id:
                    cours_inst.domaine = domaine_inst
                    modifie = True

                if modifie:
                    cours_inst.save()
                    details['cours_modifies'] += 1
                    rapport['cours_modifies'] += 1
                    log(f"🔄 Cours '{cours_inst.nom}' mis à jour dans '{classe_inst}'")
            else:
                # ---- Créer le cours d'instance ----
                base_code = cours_ref.code
                code_candidat = base_code
                suffix = 1
                while Cours.objects.filter(code=code_candidat).exists():
                    code_candidat = f"{base_code}_{suffix}"
                    suffix += 1

                cours_inst = Cours.objects.create(
                    nom=cours_ref.nom,
                    code=code_candidat,
                    coefficient=cours_ref.coefficient,
                    description=cours_ref.description,
                    niveau=niveau_inst,
                    classe=classe_inst,
                    domaine=domaine_inst,
                    ecole=ecole,
                    est_reference=False,
                    reference_source=cours_ref,
                )
                details['cours_ajoutes'] += 1
                rapport['cours_ajoutes'] += 1
                log(f"➕ Cours '{cours_ref.nom}' ajouté à '{classe_inst}'")

            # ---- Cycle d'évaluation ----
            cycle_inst, created = CycleEvaluation.objects.get_or_create(
                cours=cours_inst,
                defaults={'type_cycle': cycle_ref.type_cycle},
            )
            if not created and cycle_inst.type_cycle != cycle_ref.type_cycle:
                cycle_inst.type_cycle = cycle_ref.type_cycle
                cycle_inst.save()

            doublons = cycle_inst.nettoyer_evaluations()
            rapport['doublons_nettoyes'] += doublons

            configs_inst = {
                (c.cycle_num, c.periode_num, c.type): c
                for c in cycle_inst.evaluations.all()
            }

            # Supprimer les configs orphelines (sans notes)
            for key, config_inst in list(configs_inst.items()):
                if key not in configs_ref:
                    has_notes = EvaluationResultat.objects.filter(
                        evaluation_config=config_inst
                    ).exists()
                    if not has_notes:
                        config_inst.delete()
                        details['evaluations_supprimees'] += 1
                        rapport['evaluations_supprimees'] += 1
                    else:
                        details['erreurs'].append(
                            f"Config orpheline conservée (notes existantes) pour "
                            f"'{cours_ref.nom}' cycle {config_inst.cycle_num}."
                        )
                        rapport['evaluations_bloquees'] += 1

            # Mettre à jour ou créer les configs
            for key, config_ref in configs_ref.items():
                if key in configs_inst:
                    ci = configs_inst[key]
                    changed = False
                    if ci.points_max != config_ref.points_max:
                        ci.points_max = config_ref.points_max
                        changed = True
                    if ci.ordre != config_ref.ordre:
                        ci.ordre = config_ref.ordre
                        changed = True
                    if changed:
                        ci.save()
                        details['evaluations_modifiees'] += 1
                        rapport['evaluations_modifiees'] += 1
                else:
                    EvaluationConfig.objects.create(
                        cycle_evaluation=cycle_inst,
                        cycle_num=config_ref.cycle_num,
                        periode_num=config_ref.periode_num,
                        type=config_ref.type,
                        points_max=config_ref.points_max,
                        ordre=config_ref.ordre,
                    )
                    details['evaluations_ajoutees'] += 1
                    rapport['evaluations_ajoutees'] += 1

        except Exception as e:
            details['erreurs'].append(f"Erreur : {str(e)}")
            rapport['erreurs'].append(str(e))
            rapport['success'] = False
            log(f"❌ Erreur sur '{classe_inst}' : {e}")

        rapport['details_ecoles'].append(details)

    log(f"✅ Rapport : {rapport['cours_ajoutes']} ajouté(s), {rapport['cours_modifies']} modifié(s)")

    if rapport['evaluations_bloquees'] > 0:
        rapport['success'] = False
        rapport['message'] = (
            "Certaines configurations protégées par des notes existantes "
            "ont été conservées."
        )

    return rapport


def synchroniser_classe_ref_vers_instances(classe_ref, logger=None):
    """
    Synchronise TOUS les cours de référence d'une classe vers ses instances.
    Utilise `synchroniser_cours_ref_vers_instances` en boucle.
    """
    from ecoles.models import Cours

    if not classe_ref.est_reference or classe_ref.ecole is not None:
        return None

    cours_ref_qs = Cours.objects.filter(
        classe=classe_ref,
        ecole=None,
        est_reference=True,
    )

    if not cours_ref_qs.exists():
        return {
            'success': True,
            'classe_ref': str(classe_ref),
            'niveau_ref': str(classe_ref.niveau),
            'instances_traitees': 0,
            'cours_ajoutes': 0,
            'cours_modifies': 0,
            'message': "Aucun cours de référence pour cette classe.",
        }

    rapport_global = None
    for cours_ref in cours_ref_qs:
        rapport = synchroniser_cours_ref_vers_instances(cours_ref, logger=logger)
        if not rapport:
            continue

        if rapport_global is None:
            rapport_global = rapport
        else:
            rapport_global['cours_ajoutes'] += rapport.get('cours_ajoutes', 0)
            rapport_global['cours_modifies'] += rapport.get('cours_modifies', 0)
            rapport_global['evaluations_ajoutees'] += rapport.get('evaluations_ajoutees', 0)
            rapport_global['evaluations_modifiees'] += rapport.get('evaluations_modifiees', 0)
            rapport_global['evaluations_supprimees'] += rapport.get('evaluations_supprimees', 0)
            rapport_global['evaluations_bloquees'] += rapport.get('evaluations_bloquees', 0)
            rapport_global['doublons_nettoyes'] += rapport.get('doublons_nettoyes', 0)
            rapport_global['details_ecoles'].extend(rapport.get('details_ecoles', []))
            rapport_global['erreurs'].extend(rapport.get('erreurs', []))

    return rapport_global