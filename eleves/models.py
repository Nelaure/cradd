from django.db import models
from django.core.validators import FileExtensionValidator
from django.utils import timezone
from ecoles.models import SoftDeleteMixin, SoftDeleteManager

class Eleve(SoftDeleteMixin):
    SEXE_CHOICES = [('M', 'Masculin'), ('F', 'Féminin')]
    nom = models.CharField(max_length=100)
    postnom = models.CharField(max_length=100, blank=True)
    prenom = models.CharField(max_length=100)
    sexe = models.CharField(max_length=1, choices=SEXE_CHOICES)
    date_naissance = models.DateField(null=True, blank=True)
    lieu_naissance = models.CharField(max_length=100, blank=True)
    telephone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    adresse = models.TextField(blank=True)
    matricule = models.CharField(max_length=50, unique=True)
    ecole = models.ForeignKey('ecoles.Ecole', on_delete=models.CASCADE, related_name='eleves')
    niveau = models.ForeignKey('ecoles.Niveau', on_delete=models.CASCADE, related_name='eleves')
    classe = models.ForeignKey('ecoles.Classe', on_delete=models.CASCADE, related_name='eleves')
    annee_scolaire = models.ForeignKey('ecoles.AnneeScolaire', on_delete=models.CASCADE, related_name='eleves')
    date_inscription = models.DateField(auto_now_add=True)
    photo = models.ImageField(upload_to='photos/eleves/', blank=True, null=True)

    objects = SoftDeleteManager()
    all_objects = models.Manager()

    def __str__(self):
        return self.get_nom_complet()

    def get_nom_complet(self):
        return f"{self.nom} {self.postnom} {self.prenom}".strip()


class ParcoursEleve(models.Model):
    eleve = models.ForeignKey(Eleve, on_delete=models.CASCADE, related_name='parcours')
    annee_scolaire = models.ForeignKey('ecoles.AnneeScolaire', on_delete=models.CASCADE, related_name='parcours')
    ecole = models.ForeignKey('ecoles.Ecole', on_delete=models.CASCADE)
    niveau = models.ForeignKey('ecoles.Niveau', on_delete=models.CASCADE)
    classe = models.ForeignKey('ecoles.Classe', on_delete=models.CASCADE)
    date_debut = models.DateField()
    date_fin = models.DateField(null=True, blank=True)
    est_actuel = models.BooleanField(default=False)

    class Meta:
        unique_together = [['eleve', 'annee_scolaire']]
        ordering = ['-annee_scolaire__annee']
        indexes = [
            models.Index(fields=['eleve', 'annee_scolaire']),
            models.Index(fields=['ecole', 'annee_scolaire']),
        ]

    def __str__(self):
        return f"{self.eleve} - {self.annee_scolaire.annee}"


class MasquageEvaluation(models.Model):
    eleve = models.ForeignKey(Eleve, on_delete=models.CASCADE, related_name='masquages')
    annee_scolaire = models.ForeignKey('ecoles.AnneeScolaire', on_delete=models.CASCADE)
    evaluation_config = models.ForeignKey('ecoles.EvaluationConfig', on_delete=models.CASCADE)
    masque = models.BooleanField(default=True)
    date_modification = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [['eleve', 'annee_scolaire', 'evaluation_config']]
        indexes = [
            models.Index(fields=['eleve', 'annee_scolaire', 'evaluation_config']),
        ]

    def __str__(self):
        return f"{self.eleve} - {self.evaluation_config} - {'Masqué' if self.masque else 'Visible'}"


class MasquageColonne(models.Model):
    """
    Permet de masquer une colonne entière (période ou examen) pour un élève,
    pour un cours, un cycle, et une année donnés.
    """
    eleve = models.ForeignKey(Eleve, on_delete=models.CASCADE, related_name='masquages_colonnes')
    annee_scolaire = models.ForeignKey('ecoles.AnneeScolaire', on_delete=models.CASCADE)
    cours = models.ForeignKey('ecoles.Cours', on_delete=models.CASCADE)
    cycle_num = models.PositiveSmallIntegerField()
    type = models.CharField(max_length=10, choices=[('periode', 'Période'), ('examen', 'Examen')])
    periode_num = models.PositiveSmallIntegerField(null=True, blank=True)  # pour les périodes
    masque = models.BooleanField(default=True)
    date_modification = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [['eleve', 'annee_scolaire', 'cours', 'cycle_num', 'type', 'periode_num']]
        indexes = [
            models.Index(fields=['eleve', 'annee_scolaire', 'cours', 'cycle_num']),
        ]

    def __str__(self):
        label = f"Cycle {self.cycle_num}"
        if self.type == 'periode':
            label += f" Période {self.periode_num}"
        else:
            label += " Examen"
        return f"{self.eleve} - {self.cours} - {label} {'Masqué' if self.masque else 'Visible'}"


class Bulletin(models.Model):
    eleve = models.ForeignKey(Eleve, on_delete=models.CASCADE, related_name='bulletins')
    annee_scolaire = models.ForeignKey('ecoles.AnneeScolaire', on_delete=models.CASCADE, related_name='bulletins')
    fichier = models.FileField(upload_to='bulletins/', validators=[FileExtensionValidator(['pdf', 'png', 'jpg', 'jpeg'])])
    date_upload = models.DateTimeField(auto_now_add=True)
    description = models.TextField(blank=True)
    upload_par = models.ForeignKey('accounts.Utilisateur', on_delete=models.SET_NULL, null=True)

    class Meta:
        unique_together = [['eleve', 'annee_scolaire']]

    def __str__(self):
        return f"Bulletin de {self.eleve} - {self.annee_scolaire}"