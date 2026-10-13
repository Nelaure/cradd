from django.db import models
from django.db.models import Q
from django.db import transaction
from django.core.validators import MinValueValidator
from django.core.exceptions import ValidationError
from django.utils import timezone
from decimal import Decimal


# ===================== SOFT DELETE MIXIN =====================
class SoftDeleteManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)


class SoftDeleteMixin(models.Model):
    deleted_at = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        abstract = True

    def delete(self, using=None, keep_parents=False):
        self.deleted_at = timezone.now()
        self.save()

    def restore(self):
        self.deleted_at = None
        self.save()

    @property
    def is_deleted(self):
        return self.deleted_at is not None


# ===================== FONCTION UTILITAIRE =====================
def generer_code_unique(base_code, model_class=None):
    """Génère un code unique pour un modèle donné (par défaut Cours)."""
    if model_class is None:
        model_class = Cours
    if not base_code:
        base_code = "COURS"
    code = base_code
    suffix = 1
    while model_class.objects.filter(code=code).exists():
        code = f"{base_code}_{suffix}"
        suffix += 1
    return code


# ===================== PROVINCE =====================
class Province(SoftDeleteMixin):
    nom = models.CharField(max_length=100, unique=True)
    code = models.CharField(max_length=10, unique=True)
    description = models.TextField(blank=True)

    objects = SoftDeleteManager()
    all_objects = models.Manager()

    def __str__(self):
        return self.nom


# ===================== SECTION =====================
class Section(models.Model):
    nom = models.CharField(max_length=100)
    code = models.CharField(max_length=20, unique=True, null=True, blank=True)
    description = models.TextField(blank=True)
    ordre = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['ordre', 'nom']

    def __str__(self):
        return self.nom


# ===================== ECOLE =====================
class Ecole(SoftDeleteMixin):
    TYPE_GESTION_CHOICES = (
        ('public', 'Publique'),
        ('prive', 'Privée'),
        ('conventionne', 'Conventionné'),
    )

    nom = models.CharField(max_length=200, unique=True)
    code = models.CharField(max_length=20, unique=True)
    province = models.ForeignKey(Province, on_delete=models.PROTECT, related_name='ecoles')
    type_gestion = models.CharField(max_length=20, choices=TYPE_GESTION_CHOICES, default='public')
    responsable = models.CharField(max_length=200, blank=True)
    contact = models.CharField(max_length=20, blank=True)
    adresse = models.TextField(blank=True)
    telephone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    est_active = models.BooleanField(default=True)

    objects = SoftDeleteManager()
    all_objects = models.Manager()

    class Meta:
        indexes = [
            models.Index(fields=['province', 'est_active']),
        ]

    def __str__(self):
        return self.nom


# ===================== NIVEAU =====================
class Niveau(SoftDeleteMixin):
    nom = models.CharField(max_length=50)
    description = models.TextField(blank=True)
    ordre = models.PositiveSmallIntegerField(default=0)
    ecole = models.ForeignKey(Ecole, on_delete=models.CASCADE, null=True, blank=True, related_name='niveaux')
    est_reference = models.BooleanField(default=False)
    section = models.ForeignKey(Section, on_delete=models.SET_NULL, null=True, blank=True, related_name='niveaux')

    # Lien vers la référence d'origine (pour les instances uniquement)
    reference_source = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='instances',
        limit_choices_to={'est_reference': True},
        help_text="Référence d'origine (uniquement pour les instances)"
    )

    objects = SoftDeleteManager()
    all_objects = models.Manager()

    class Meta:
        unique_together = [['nom', 'ecole', 'section']]
        indexes = [
            models.Index(fields=['ecole', 'est_reference']),
            models.Index(fields=['section']),
            models.Index(fields=['reference_source']),
        ]

    def __str__(self):
        base = f"{self.nom}"
        if self.section:
            base += f" - {self.section.nom}"
        return base + (" (réf.)" if self.est_reference else "")

    def clean(self):
        if self.est_reference and self.ecole is not None:
            raise ValidationError("Une référence ne peut pas être associée à une école.")
        if not self.est_reference and self.ecole is None:
            raise ValidationError("Une instance doit être associée à une école.")
        if self.est_reference and self.ecole is None and self.section is not None:
            existing = Niveau.objects.filter(
                est_reference=True,
                ecole__isnull=True,
                nom=self.nom,
                section=self.section
            ).exclude(pk=self.pk).exists()
            if existing:
                raise ValidationError(
                    f"Un niveau de référence avec le nom '{self.nom}' et la section '{self.section.nom}' existe déjà."
                )

    # ---------- RÉCUPÉRATION DES INSTANCES ----------
    def get_instances(self):
        """
        Retourne toutes les instances de ce niveau de référence.
        Utilise `reference_source` si disponible, sinon fallback par `nom + section`.
        Ce fallback garantit que les anciennes instances (créées avant l'ajout
        du champ `reference_source`) restent synchronisables.
        """
        if not self.est_reference or self.ecole is not None:
            return Niveau.objects.none()

        return Niveau.objects.filter(
            est_reference=False,
            ecole__isnull=False,
        ).filter(
            Q(reference_source=self) |
            Q(reference_source__isnull=True, nom=self.nom, section=self.section)
        )

    def get_instances_count(self):
        """Compte rapide sans charger les objets."""
        return self.get_instances().count()

    # ---------- AFFECTATION ----------
    @transaction.atomic
    def affecter_a_ecole(self, ecole, section=None):
        """
        Copie ce niveau de référence vers une école.
        Crée un nouveau niveau + ses classes + ses cours + ses évaluations.
        Lie toutes les entités créées à leur référence d'origine.
        Transaction atomique : tout ou rien.
        """
        if not self.est_reference or self.ecole is not None:
            raise ValueError("Seul un niveau de référence peut être affecté à une école.")

        section_a_utiliser = section if section is not None else self.section

        if Niveau.objects.filter(
            nom=self.nom,
            ecole=ecole,
            section=section_a_utiliser,
            est_reference=False
        ).exists():
            raise ValidationError(
                f"Le niveau '{self.nom}' avec la section "
                f"'{section_a_utiliser.nom if section_a_utiliser else '-'}' "
                f"existe déjà dans cette école."
            )

        nouveau_niveau = Niveau.objects.create(
            nom=self.nom,
            description=self.description,
            ordre=self.ordre,
            ecole=ecole,
            est_reference=False,
            section=section_a_utiliser,
            reference_source=self,
        )

        classes_ref = Classe.objects.filter(niveau=self, ecole=None, est_reference=True)
        for classe_ref in classes_ref:
            nouvelle_classe = Classe.objects.create(
                nom=classe_ref.nom,
                description=classe_ref.description,
                ordre=classe_ref.ordre,
                niveau=nouveau_niveau,
                ecole=ecole,
                est_reference=False,
                reference_source=classe_ref,
            )
            self._copier_cours(classe_ref, nouvelle_classe, ecole, nouveau_niveau)

        return nouveau_niveau

    def _copier_cours(self, classe_ref, nouvelle_classe, ecole, nouveau_niveau):
        """Copie les cours d'une classe de référence vers une instance (sans domaine)."""
        cours_ref_qs = Cours.objects.filter(classe=classe_ref, ecole=None, est_reference=True)

        for cours_ref in cours_ref_qs:
            # --- Code unique ---
            base_code = cours_ref.code
            code_candidat = base_code
            suffix = 1
            while Cours.objects.filter(code=code_candidat).exists():
                code_candidat = f"{base_code}_{suffix}"
                suffix += 1

            # --- Cours ---
            nouveau_cours = Cours.objects.create(
                nom=cours_ref.nom,
                code=code_candidat,
                coefficient=cours_ref.coefficient,
                description=cours_ref.description,
                niveau=nouveau_niveau,
                classe=nouvelle_classe,
                ecole=ecole,
                est_reference=False,
                reference_source=cours_ref,
            )

            # --- Cycle d'évaluation ---
            cycle_ref, _ = CycleEvaluation.objects.get_or_create(cours=cours_ref)
            if not cycle_ref.evaluations.exists():
                cycle_ref.creer_evaluations_par_defaut()

            nouveau_cycle = CycleEvaluation.objects.create(
                cours=nouveau_cours,
                type_cycle=cycle_ref.type_cycle
            )
            nouveau_cycle.evaluations.all().delete()
            for config_ref in cycle_ref.evaluations.all():
                EvaluationConfig.objects.create(
                    cycle_evaluation=nouveau_cycle,
                    cycle_num=config_ref.cycle_num,
                    periode_num=config_ref.periode_num,
                    type=config_ref.type,
                    points_max=config_ref.points_max,
                    ordre=config_ref.ordre
                )

    # ---------- SYNCHRONISATION ----------
    def synchroniser_vers_ecoles(self, **kwargs):
        """
        Synchronise ce niveau de référence vers TOUTES ses instances.
        Utilise get_instances() qui applique un fallback pour les anciennes
        instances dont reference_source est null.
        """
        force_delete = kwargs.get('force_delete_notes', False)

        if not self.est_reference or self.ecole is not None:
            return {
                'success': False,
                'message': "Seul un niveau de référence peut être synchronisé."
            }

        rapport = {
            'success': True,
            'niveau_ref': str(self),
            'instances_traitees': 0,
            'classes_ajoutees': 0,
            'classes_modifiees': 0,
            'cours_ajoutes': 0,
            'cours_modifies': 0,
            'evaluations_ajoutees': 0,
            'evaluations_modifiees': 0,
            'evaluations_supprimees': 0,
            'evaluations_bloquees': 0,
            'doublons_nettoyes': 0,
            'erreurs': [],
            'details_ecoles': [],
        }

        # Fallback robuste : trouve les instances même si reference_source est null
        instances = self.get_instances()

        if not instances.exists():
            rapport['success'] = True
            rapport['message'] = "Aucune instance à synchroniser pour cette référence."
            return rapport

        for niveau_instance in instances:
            ecole = niveau_instance.ecole

            # ⚠️ AUTO-RÉPARATION : on lie l'instance si ce n'est pas déjà fait
            if niveau_instance.reference_source_id is None:
                niveau_instance.reference_source = self
                niveau_instance.save(update_fields=['reference_source'])

            details_ecole = {
                'ecole': ecole.nom,
                'classes_traitees': 0,
                'classes_ajoutees': 0,
                'classes_modifiees': 0,
                'cours_ajoutes': 0,
                'cours_modifies': 0,
                'evaluations_ajoutees': 0,
                'evaluations_modifiees': 0,
                'evaluations_supprimees': 0,
                'erreurs': [],
            }

            classes_ref = Classe.objects.filter(
                niveau=self,
                ecole=None,
                est_reference=True
            )

            for classe_ref in classes_ref:
                # --- Classe (avec fallback) ---
                classe_instance = Classe.objects.filter(
                    ecole=ecole,
                    est_reference=False,
                ).filter(
                    Q(reference_source=classe_ref) |
                    Q(reference_source__isnull=True,
                      nom=classe_ref.nom,
                      niveau__nom=niveau_instance.nom,
                      niveau__section=niveau_instance.section)
                ).first()

                if classe_instance:
                    # Auto-réparation
                    if classe_instance.reference_source_id is None:
                        classe_instance.reference_source = classe_ref
                        classe_instance.save(update_fields=['reference_source'])

                    modifie = False
                    if classe_instance.description != classe_ref.description:
                        classe_instance.description = classe_ref.description
                        modifie = True
                    if classe_instance.ordre != classe_ref.ordre:
                        classe_instance.ordre = classe_ref.ordre
                        modifie = True
                    if classe_instance.nom != classe_ref.nom:
                        classe_instance.nom = classe_ref.nom
                        modifie = True
                    if classe_instance.niveau_id != niveau_instance.id:
                        classe_instance.niveau = niveau_instance
                        modifie = True
                    if modifie:
                        classe_instance.save()
                        details_ecole['classes_modifiees'] += 1
                        rapport['classes_modifiees'] += 1
                else:
                    classe_instance = Classe.objects.create(
                        nom=classe_ref.nom,
                        description=classe_ref.description,
                        ordre=classe_ref.ordre,
                        niveau=niveau_instance,
                        ecole=ecole,
                        est_reference=False,
                        reference_source=classe_ref,
                    )
                    details_ecole['classes_ajoutees'] += 1
                    rapport['classes_ajoutees'] += 1

                details_ecole['classes_traitees'] += 1

                # --- Cours (sans domaine) ---
                cours_ref_queryset = Cours.objects.filter(
                    classe=classe_ref,
                    ecole=None,
                    est_reference=True
                )

                for cours_ref in cours_ref_queryset:
                    # Fallback robuste
                    cours_existant = Cours.objects.filter(
                        ecole=ecole,
                        est_reference=False,
                    ).filter(
                        Q(reference_source=cours_ref) |
                        Q(reference_source__isnull=True,
                          nom=cours_ref.nom,
                          classe=classe_instance)
                    ).first()

                    if cours_existant:
                        # Auto-réparation
                        if cours_existant.reference_source_id is None:
                            cours_existant.reference_source = cours_ref
                            cours_existant.save(update_fields=['reference_source'])

                        modifie = False
                        if cours_existant.coefficient != cours_ref.coefficient:
                            cours_existant.coefficient = cours_ref.coefficient
                            modifie = True
                        if cours_existant.description != cours_ref.description:
                            cours_existant.description = cours_ref.description
                            modifie = True
                        if cours_existant.nom != cours_ref.nom:
                            cours_existant.nom = cours_ref.nom
                            modifie = True
                        if cours_existant.classe_id != classe_instance.id:
                            cours_existant.classe = classe_instance
                            modifie = True
                        if cours_existant.niveau_id != niveau_instance.id:
                            cours_existant.niveau = niveau_instance
                            modifie = True
                        if modifie:
                            cours_existant.save()
                            details_ecole['cours_modifies'] += 1
                            rapport['cours_modifies'] += 1
                        cours_instance = cours_existant
                    else:
                        base_code = cours_ref.code
                        code_candidat = base_code
                        suffix = 1
                        while Cours.objects.filter(code=code_candidat).exists():
                            code_candidat = f"{base_code}_{suffix}"
                            suffix += 1

                        cours_instance = Cours.objects.create(
                            nom=cours_ref.nom,
                            code=code_candidat,
                            coefficient=cours_ref.coefficient,
                            description=cours_ref.description,
                            niveau=niveau_instance,
                            classe=classe_instance,
                            ecole=ecole,
                            est_reference=False,
                            reference_source=cours_ref,
                        )
                        details_ecole['cours_ajoutes'] += 1
                        rapport['cours_ajoutes'] += 1

                    # --- Cycle d'évaluation ---
                    cycle_ref, _ = CycleEvaluation.objects.get_or_create(cours=cours_ref)
                    if not cycle_ref.evaluations.exists():
                        cycle_ref.creer_evaluations_par_defaut()

                    cycle_instance, cycle_created = CycleEvaluation.objects.get_or_create(
                        cours=cours_instance,
                        defaults={'type_cycle': cycle_ref.type_cycle}
                    )
                    if not cycle_created and cycle_instance.type_cycle != cycle_ref.type_cycle:
                        cycle_instance.type_cycle = cycle_ref.type_cycle
                        cycle_instance.save()

                    doublons_supprimes = cycle_instance.nettoyer_evaluations()
                    rapport['doublons_nettoyes'] += doublons_supprimes

                    configs_ref = {
                        (c.cycle_num, c.periode_num, c.type): c
                        for c in cycle_ref.evaluations.all()
                    }
                    configs_inst = {
                        (c.cycle_num, c.periode_num, c.type): c
                        for c in cycle_instance.evaluations.all()
                    }

                    # Supprimer les configs orphelines
                    for key, config_inst in list(configs_inst.items()):
                        if key not in configs_ref:
                            has_notes = EvaluationResultat.objects.filter(
                                evaluation_config=config_inst
                            ).exists()
                            if has_notes:
                                if force_delete:
                                    EvaluationResultat.objects.filter(
                                        evaluation_config=config_inst
                                    ).delete()
                                    config_inst.delete()
                                    details_ecole['evaluations_supprimees'] += 1
                                    rapport['evaluations_supprimees'] += 1
                                else:
                                    details_ecole['erreurs'].append(
                                        f"Config orpheline pour '{cours_ref.nom}' "
                                        f"(cycle {config_inst.cycle_num}, "
                                        f"{config_inst.get_type_display()}) : notes existantes."
                                    )
                                    rapport['evaluations_bloquees'] += 1
                            else:
                                config_inst.delete()
                                details_ecole['evaluations_supprimees'] += 1
                                rapport['evaluations_supprimees'] += 1

                    # Mettre à jour ou ajouter
                    for key, config_ref in configs_ref.items():
                        if key in configs_inst:
                            config_inst = configs_inst[key]
                            if config_ref.points_max != config_inst.points_max:
                                notes = EvaluationResultat.objects.filter(
                                    evaluation_config=config_inst
                                )
                                if notes.filter(
                                    points_obtenus__gt=config_ref.points_max
                                ).exists():
                                    details_ecole['erreurs'].append(
                                        f"Impossible de réduire points_max à "
                                        f"{config_ref.points_max} pour '{cours_ref.nom}' "
                                        f"(notes supérieures existantes)."
                                    )
                                    rapport['evaluations_bloquees'] += 1
                                else:
                                    config_inst.points_max = config_ref.points_max
                                    config_inst.ordre = config_ref.ordre
                                    config_inst.save()
                                    details_ecole['evaluations_modifiees'] += 1
                                    rapport['evaluations_modifiees'] += 1
                            elif config_inst.ordre != config_ref.ordre:
                                config_inst.ordre = config_ref.ordre
                                config_inst.save()
                                details_ecole['evaluations_modifiees'] += 1
                                rapport['evaluations_modifiees'] += 1
                        else:
                            EvaluationConfig.objects.create(
                                cycle_evaluation=cycle_instance,
                                cycle_num=config_ref.cycle_num,
                                periode_num=config_ref.periode_num,
                                type=config_ref.type,
                                points_max=config_ref.points_max,
                                ordre=config_ref.ordre
                            )
                            details_ecole['evaluations_ajoutees'] += 1
                            rapport['evaluations_ajoutees'] += 1

            rapport['details_ecoles'].append(details_ecole)
            rapport['instances_traitees'] += 1

        if rapport['evaluations_bloquees'] > 0:
            rapport['success'] = False
            rapport['message'] = (
                "Des conflits de notes ont empêché certaines mises à jour. Voir détails."
            )

        if rapport['doublons_nettoyes'] > 0:
            rapport['message'] = rapport.get('message', '') + (
                f" {rapport['doublons_nettoyes']} doublon(s) nettoyé(s)."
            )

        return rapport

    # ---------- SYNCHRONISATION AUTOMATIQUE ----------
    def synchroniser_si_necessaire(self, **kwargs):
        """
        Synchronise ce niveau de référence vers ses instances SI elles existent.
        Retourne None si aucune instance, sinon le rapport.
        """
        if not self.est_reference or self.ecole is not None:
            return None

        if not self.get_instances().exists():
            return None

        return self.synchroniser_vers_ecoles(**kwargs)


# ===================== CLASSE =====================
class Classe(SoftDeleteMixin):
    nom = models.CharField(max_length=50)
    description = models.TextField(blank=True)
    ordre = models.PositiveSmallIntegerField(default=0)
    niveau = models.ForeignKey(Niveau, on_delete=models.CASCADE, related_name='classes')
    ecole = models.ForeignKey(Ecole, on_delete=models.CASCADE, null=True, blank=True, related_name='classes')
    est_reference = models.BooleanField(default=False)

    reference_source = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='instances',
        limit_choices_to={'est_reference': True},
        help_text="Classe de référence d'origine (uniquement pour les instances)"
    )

    objects = SoftDeleteManager()
    all_objects = models.Manager()

    class Meta:
        unique_together = [['nom', 'niveau', 'ecole']]
        indexes = [
            models.Index(fields=['niveau', 'ecole', 'est_reference']),
            models.Index(fields=['reference_source']),
        ]

    def __str__(self):
        return f"{self.nom} ({self.niveau.nom})" + (" (réf.)" if self.est_reference else "")

    def clean(self):
        if self.est_reference and self.ecole is not None:
            raise ValidationError("Une référence ne peut pas être associée à une école.")
        if not self.est_reference and self.ecole is None:
            raise ValidationError("Une instance doit être associée à une école.")


# ===================== COURS (SANS DOMAINE) =====================
class Cours(SoftDeleteMixin):
    nom = models.CharField(max_length=100)
    code = models.CharField(max_length=20, unique=True)
    coefficient = models.PositiveIntegerField(default=1)
    description = models.TextField(blank=True)
    niveau = models.ForeignKey(Niveau, on_delete=models.CASCADE, related_name='cours')
    classe = models.ForeignKey(Classe, on_delete=models.CASCADE, related_name='cours')
    ecole = models.ForeignKey(Ecole, on_delete=models.CASCADE, null=True, blank=True, related_name='cours')
    est_reference = models.BooleanField(default=False)

    reference_source = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='instances',
        limit_choices_to={'est_reference': True},
        help_text="Cours de référence d'origine (uniquement pour les instances)"
    )

    date_creation = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    date_modification = models.DateTimeField(auto_now=True, null=True, blank=True)

    objects = SoftDeleteManager()
    all_objects = models.Manager()

    class Meta:
        unique_together = [['nom', 'niveau', 'classe', 'ecole']]
        indexes = [
            models.Index(fields=['niveau', 'classe', 'ecole', 'est_reference']),
            models.Index(fields=['-date_creation']),
            models.Index(fields=['reference_source']),
        ]

    def __str__(self):
        return f"{self.nom} ({self.classe.nom})" + (" (réf.)" if self.est_reference else "")

    def clean(self):
        if self.est_reference and self.ecole is not None:
            raise ValidationError("Une référence ne peut pas être associée à une école.")
        if not self.est_reference and self.ecole is None:
            raise ValidationError("Une instance doit être associée à une école.")


# ===================== ANNÉE SCOLAIRE =====================
class AnneeScolaire(models.Model):
    annee = models.CharField(max_length=9, unique=True)
    date_debut = models.DateField()
    date_fin = models.DateField()
    est_actuelle = models.BooleanField(default=False)
    ecoles = models.ManyToManyField(Ecole, related_name='annees_scolaires')

    class Meta:
        indexes = [
            models.Index(fields=['est_actuelle']),
        ]

    def __str__(self):
        return self.annee

    def save(self, *args, **kwargs):
        if self.est_actuelle:
            AnneeScolaire.objects.filter(est_actuelle=True).update(est_actuelle=False)
        super().save(*args, **kwargs)


# ===================== CYCLE D'ÉVALUATION =====================
class CycleEvaluation(models.Model):
    """
    Cycle d'évaluation lié à un cours.

    RÈGLES IMPORTANTES :
    1. `save()` ne crée JAMAIS d'évaluations automatiquement.
    2. `creer_evaluations_par_defaut()` ne s'exécute QUE si AUCUNE n'existe.
    3. `nettoyer_evaluations()` supprime UNIQUEMENT les doublons.
    4. Examen = 2 × points_max des périodes.
    """

    CYCLE_TYPES = (
        ('trimestre', 'Trimestriel'),
        ('semestre', 'Semestriel'),
    )

    cours = models.OneToOneField(Cours, on_delete=models.CASCADE, related_name='cycle_evaluation')
    type_cycle = models.CharField(max_length=20, choices=CYCLE_TYPES, default='trimestre')

    def get_nombre_cycles(self):
        return 3 if self.type_cycle == 'trimestre' else 2

    def creer_evaluations_par_defaut(self):
        if self.evaluations.exists():
            return

        nb = self.get_nombre_cycles()
        points_periode = 20
        points_examen = points_periode * 2

        for cycle in range(1, nb + 1):
            for periode in [1, 2]:
                EvaluationConfig.objects.create(
                    cycle_evaluation=self,
                    cycle_num=cycle,
                    periode_num=periode,
                    type='periode',
                    points_max=points_periode,
                    ordre=periode
                )
            EvaluationConfig.objects.create(
                cycle_evaluation=self,
                cycle_num=cycle,
                periode_num=None,
                type='examen',
                points_max=points_examen,
                ordre=3
            )

    def nettoyer_evaluations(self):
        nb_cycles = self.get_nombre_cycles()
        configs = self.evaluations.filter(
            cycle_num__lte=nb_cycles
        ).order_by('cycle_num', 'ordre')
        unique = {}
        deleted_count = 0

        for config in configs:
            if config.type == 'periode' and config.periode_num is None:
                config.delete()
                deleted_count += 1
                continue
            if config.type not in ['periode', 'examen']:
                config.delete()
                deleted_count += 1
                continue

            key = (config.cycle_num, config.periode_num, config.type)
            if key in unique:
                config.delete()
                deleted_count += 1
            else:
                unique[key] = config

        return deleted_count

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)


# ===================== CONFIGURATION D'ÉVALUATION =====================
class EvaluationConfig(models.Model):
    TYPE_CHOICES = (
        ('periode', 'Période'),
        ('examen', 'Examen'),
    )
    cycle_evaluation = models.ForeignKey(
        CycleEvaluation,
        on_delete=models.CASCADE,
        related_name='evaluations'
    )
    cycle_num = models.PositiveSmallIntegerField()
    periode_num = models.PositiveSmallIntegerField(null=True, blank=True)
    type = models.CharField(max_length=10, choices=TYPE_CHOICES)
    points_max = models.PositiveIntegerField(default=20)
    ordre = models.PositiveSmallIntegerField(default=0)

    class Meta:
        unique_together = [['cycle_evaluation', 'cycle_num', 'periode_num', 'type']]
        ordering = ['cycle_num', 'ordre']

    def __str__(self):
        label = f"Cycle {self.cycle_num} - "
        label += f"Période {self.periode_num}" if self.type == 'periode' else "Examen"
        return f"{label} ({self.points_max} pts)"


# ===================== RÉSULTAT D'ÉVALUATION =====================
class EvaluationResultat(models.Model):
    eleve = models.ForeignKey(
        'eleves.Eleve',
        on_delete=models.CASCADE,
        related_name='evaluation_resultats'
    )
    cours = models.ForeignKey(
        Cours,
        on_delete=models.CASCADE,
        related_name='evaluation_resultats'
    )
    annee_scolaire = models.ForeignKey(
        AnneeScolaire,
        on_delete=models.CASCADE,
        related_name='evaluation_resultats'
    )
    evaluation_config = models.ForeignKey(
        EvaluationConfig,
        on_delete=models.CASCADE,
        related_name='resultats'
    )
    points_obtenus = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        validators=[MinValueValidator(0)]
    )
    date_saisie = models.DateTimeField(auto_now_add=True)
    date_modification = models.DateTimeField(auto_now=True)
    saisie_par = models.ForeignKey(
        'accounts.Utilisateur',
        on_delete=models.SET_NULL,
        null=True,
        related_name='eval_resultats_saisis'
    )

    class Meta:
        unique_together = [['eleve', 'cours', 'annee_scolaire', 'evaluation_config']]
        indexes = [
            models.Index(fields=['eleve', 'annee_scolaire']),
            models.Index(fields=['cours', 'annee_scolaire']),
            models.Index(fields=['eleve', 'cours', 'annee_scolaire']),
        ]

    def __str__(self):
        return f"{self.eleve} - {self.cours} - {self.evaluation_config} : {self.points_obtenus}"

    @property
    def points_max(self):
        return self.evaluation_config.points_max

    @property
    def pourcentage(self):
        if self.points_max > 0:
            return round((float(self.points_obtenus) / self.points_max) * 100, 1)
        return 0.0


# ===================== RÉSULTAT CYCLE =====================
class ResultatCycle(models.Model):
    eleve = models.ForeignKey('eleves.Eleve', on_delete=models.CASCADE, related_name='resultats_cycles')
    cours = models.ForeignKey(Cours, on_delete=models.CASCADE, related_name='resultats_cycles')
    annee_scolaire = models.ForeignKey(AnneeScolaire, on_delete=models.CASCADE, related_name='resultats_cycles')
    cycle_num = models.PositiveSmallIntegerField()
    total_points_obtenus = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_points_possibles = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    pourcentage = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    moyenne_sur_20 = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    date_calcul = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [['eleve', 'cours', 'annee_scolaire', 'cycle_num']]
        indexes = [
            models.Index(fields=['eleve', 'annee_scolaire']),
            models.Index(fields=['cours', 'annee_scolaire']),
        ]

    def __str__(self):
        return f"{self.eleve} - {self.cours} - Cycle {self.cycle_num} : {self.pourcentage}%"


# ===================== RÉSULTAT ANNUEL =====================
class ResultatAnnuel(models.Model):
    eleve = models.ForeignKey('eleves.Eleve', on_delete=models.CASCADE, related_name='resultats_annuels')
    annee_scolaire = models.ForeignKey(AnneeScolaire, on_delete=models.CASCADE, related_name='resultats_annuels')
    total_points_obtenus = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_points_possibles = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    pourcentage_general = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    moyenne_generale = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    date_calcul = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [['eleve', 'annee_scolaire']]
        indexes = [
            models.Index(fields=['eleve', 'annee_scolaire']),
        ]

    def recalculer(self):
        cycles = ResultatCycle.objects.filter(
            eleve=self.eleve,
            annee_scolaire=self.annee_scolaire
        )
        total_obtenus = cycles.aggregate(
            total=models.Sum('total_points_obtenus')
        )['total'] or Decimal('0.00')
        total_possibles = cycles.aggregate(
            total=models.Sum('total_points_possibles')
        )['total'] or Decimal('0.00')

        self.total_points_obtenus = total_obtenus
        self.total_points_possibles = total_possibles
        if total_possibles > 0:
            self.pourcentage_general = (total_obtenus / total_possibles) * 100
            cours_coeffs = {}
            for cycle in cycles:
                if cycle.cours.id not in cours_coeffs:
                    cours_coeffs[cycle.cours.id] = cycle.cours.coefficient
            total_coeff = sum(cours_coeffs.values()) if cours_coeffs else 0
            if total_coeff > 0:
                weighted_sum = sum(
                    cycle.moyenne_sur_20 * cours_coeffs.get(cycle.cours.id, 1)
                    for cycle in cycles
                )
                self.moyenne_generale = weighted_sum / total_coeff
            else:
                self.moyenne_generale = 0
        else:
            self.pourcentage_general = 0
            self.moyenne_generale = 0
        self.save()