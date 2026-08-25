from django.db import models
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


# ===================== PROVINCE =====================
class Province(SoftDeleteMixin):
    nom = models.CharField(max_length=100, unique=True)
    code = models.CharField(max_length=10, unique=True)
    description = models.TextField(blank=True)

    objects = SoftDeleteManager()
    all_objects = models.Manager()

    def __str__(self):
        return self.nom


# ===================== MODÈLES =====================
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


class Niveau(SoftDeleteMixin):
    nom = models.CharField(max_length=50)
    description = models.TextField(blank=True)
    ordre = models.PositiveSmallIntegerField(default=0)
    ecole = models.ForeignKey(Ecole, on_delete=models.CASCADE, null=True, blank=True, related_name='niveaux')
    est_reference = models.BooleanField(default=False)

    objects = SoftDeleteManager()
    all_objects = models.Manager()

    class Meta:
        unique_together = [['nom', 'ecole']]
        indexes = [
            models.Index(fields=['ecole', 'est_reference']),
        ]

    def __str__(self):
        return f"{self.nom}" + (" (réf.)" if self.est_reference else "")

    def clean(self):
        if self.est_reference and self.ecole is not None:
            raise ValidationError("Une référence ne peut pas être associée à une école.")
        if not self.est_reference and self.ecole is None:
            raise ValidationError("Une instance doit être associée à une école.")

    def affecter_a_ecole(self, ecole):
        if not self.est_reference or self.ecole is not None:
            raise ValueError("Seul un niveau de référence peut être affecté à une école.")
        if Niveau.objects.filter(nom=self.nom, ecole=ecole, est_reference=False).exists():
            raise ValidationError(f"Le niveau '{self.nom}' est déjà affecté à cette école.")

        nouveau_niveau = Niveau.objects.create(
            nom=self.nom,
            description=self.description,
            ordre=self.ordre,
            ecole=ecole,
            est_reference=False
        )
        classes_ref = Classe.objects.filter(niveau=self, ecole=None, est_reference=True)
        for classe_ref in classes_ref:
            nouvelle_classe = Classe.objects.create(
                nom=classe_ref.nom,
                description=classe_ref.description,
                ordre=classe_ref.ordre,
                niveau=nouveau_niveau,
                ecole=ecole,
                est_reference=False
            )
            self._copier_domaines_et_cours(classe_ref, nouvelle_classe, ecole, nouveau_niveau)
        return nouveau_niveau

    def _copier_domaines_et_cours(self, classe_ref, nouvelle_classe, ecole, nouveau_niveau):
        cours_ref = Cours.objects.filter(classe=classe_ref, ecole=None, est_reference=True)
        for cours_ref in cours_ref:
            domaine_ref = cours_ref.domaine
            try:
                domaine_ecole = Domaine.objects.get(nom=domaine_ref.nom, ecole=ecole, est_reference=False)
            except Domaine.DoesNotExist:
                domaine_ecole = Domaine.objects.create(
                    nom=domaine_ref.nom,
                    description=domaine_ref.description,
                    ecole=ecole,
                    est_reference=False
                )

            base_code = cours_ref.code
            code_candidat = base_code
            suffix = 1
            while Cours.objects.filter(code=code_candidat).exists():
                code_candidat = f"{base_code}_{suffix}"
                suffix += 1

            nouveau_cours = Cours.objects.create(
                nom=cours_ref.nom,
                code=code_candidat,
                coefficient=cours_ref.coefficient,
                description=cours_ref.description,
                niveau=nouveau_niveau,
                classe=nouvelle_classe,
                domaine=domaine_ecole,
                ecole=ecole,
                est_reference=False
            )

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


class Classe(SoftDeleteMixin):
    nom = models.CharField(max_length=50)
    description = models.TextField(blank=True)
    ordre = models.PositiveSmallIntegerField(default=0)
    niveau = models.ForeignKey(Niveau, on_delete=models.CASCADE, related_name='classes')
    ecole = models.ForeignKey(Ecole, on_delete=models.CASCADE, null=True, blank=True, related_name='classes')
    est_reference = models.BooleanField(default=False)

    objects = SoftDeleteManager()
    all_objects = models.Manager()

    class Meta:
        unique_together = [['nom', 'niveau', 'ecole']]
        indexes = [
            models.Index(fields=['niveau', 'ecole', 'est_reference']),
        ]

    def __str__(self):
        return f"{self.nom} ({self.niveau.nom})" + (" (réf.)" if self.est_reference else "")

    def clean(self):
        if self.est_reference and self.ecole is not None:
            raise ValidationError("Une référence ne peut pas être associée à une école.")
        if not self.est_reference and self.ecole is None:
            raise ValidationError("Une instance doit être associée à une école.")


class Domaine(SoftDeleteMixin):
    nom = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    ecole = models.ForeignKey(Ecole, on_delete=models.CASCADE, null=True, blank=True, related_name='domaines')
    est_reference = models.BooleanField(default=False)
    niveaux = models.ManyToManyField(Niveau, blank=True, related_name='domaines')
    classes = models.ManyToManyField(Classe, blank=True, related_name='domaines')

    objects = SoftDeleteManager()
    all_objects = models.Manager()

    class Meta:
        unique_together = [['nom', 'ecole']]
        indexes = [
            models.Index(fields=['ecole', 'est_reference']),
        ]

    def __str__(self):
        return self.nom + (" (réf.)" if self.est_reference else "")

    def clean(self):
        if self.est_reference and self.ecole is not None:
            raise ValidationError("Une référence ne peut pas être associée à une école.")
        if not self.est_reference and self.ecole is None:
            raise ValidationError("Une instance doit être associée à une école.")


class Cours(SoftDeleteMixin):
    nom = models.CharField(max_length=100)
    code = models.CharField(max_length=20, unique=True)
    coefficient = models.PositiveIntegerField(default=1)
    description = models.TextField(blank=True)
    niveau = models.ForeignKey(Niveau, on_delete=models.CASCADE, related_name='cours')
    classe = models.ForeignKey(Classe, on_delete=models.CASCADE, related_name='cours')
    domaine = models.ForeignKey(Domaine, on_delete=models.CASCADE, related_name='cours')
    ecole = models.ForeignKey(Ecole, on_delete=models.CASCADE, null=True, blank=True, related_name='cours')
    est_reference = models.BooleanField(default=False)

    objects = SoftDeleteManager()
    all_objects = models.Manager()

    class Meta:
        unique_together = [['nom', 'niveau', 'classe', 'domaine', 'ecole']]
        indexes = [
            models.Index(fields=['niveau', 'classe', 'ecole', 'est_reference']),
        ]

    def __str__(self):
        return f"{self.nom} ({self.classe.nom})" + (" (réf.)" if self.est_reference else "")

    def clean(self):
        if self.est_reference and self.ecole is not None:
            raise ValidationError("Une référence ne peut pas être associée à une école.")
        if not self.est_reference and self.ecole is None:
            raise ValidationError("Une instance doit être associée à une école.")


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


class CycleEvaluation(models.Model):
    CYCLE_TYPES = (
        ('trimestre', 'Trimestriel'),
        ('semestre', 'Semestriel'),
    )
    cours = models.OneToOneField(Cours, on_delete=models.CASCADE, related_name='cycle_evaluation')
    type_cycle = models.CharField(max_length=20, choices=CYCLE_TYPES, default='trimestre')

    def get_nombre_cycles(self):
        return 3 if self.type_cycle == 'trimestre' else 2

    def creer_evaluations_par_defaut(self):
        nb = self.get_nombre_cycles()
        for cycle in range(1, nb+1):
            for periode in [1, 2]:
                EvaluationConfig.objects.get_or_create(
                    cycle_evaluation=self,
                    cycle_num=cycle,
                    periode_num=periode,
                    type='periode',
                    defaults={'points_max': 20, 'ordre': periode}
                )
            EvaluationConfig.objects.get_or_create(
                cycle_evaluation=self,
                cycle_num=cycle,
                periode_num=None,
                type='examen',
                defaults={'points_max': 20, 'ordre': 3}
            )

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.evaluations.exists():
            self.creer_evaluations_par_defaut()


class EvaluationConfig(models.Model):
    TYPE_CHOICES = (
        ('periode', 'Période'),
        ('examen', 'Examen'),
    )
    cycle_evaluation = models.ForeignKey(CycleEvaluation, on_delete=models.CASCADE, related_name='evaluations')
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


class EvaluationResultat(models.Model):
    eleve = models.ForeignKey('eleves.Eleve', on_delete=models.CASCADE, related_name='evaluation_resultats')
    cours = models.ForeignKey(Cours, on_delete=models.CASCADE, related_name='evaluation_resultats')
    annee_scolaire = models.ForeignKey(AnneeScolaire, on_delete=models.CASCADE, related_name='evaluation_resultats')
    evaluation_config = models.ForeignKey(EvaluationConfig, on_delete=models.CASCADE, related_name='resultats')
    points_obtenus = models.DecimalField(max_digits=5, decimal_places=2, validators=[MinValueValidator(0)])
    date_saisie = models.DateTimeField(auto_now_add=True)
    date_modification = models.DateTimeField(auto_now=True)
    saisie_par = models.ForeignKey('accounts.Utilisateur', on_delete=models.SET_NULL, null=True, related_name='eval_resultats_saisis')

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
        total_obtenus = cycles.aggregate(total=models.Sum('total_points_obtenus'))['total'] or Decimal('0.00')
        total_possibles = cycles.aggregate(total=models.Sum('total_points_possibles'))['total'] or Decimal('0.00')

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