from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone

class Utilisateur(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = 'ADMIN', 'Administrateur'
        INSPECTEUR = 'INSPECTEUR', 'Inspecteur'
        AGENT = 'AGENT', 'Agent'
        ENSEIGNANT = 'ENSEIGNANT', 'Enseignant'
        PARENT = 'PARENT', 'Parent'
        PROVED = 'PROVED', 'Directeur Provincial'

    nom = models.CharField(max_length=100)
    postnom = models.CharField(max_length=100, blank=True)
    prenom = models.CharField(max_length=100)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.ADMIN)
    ecole_affectation = models.ForeignKey(
        'ecoles.Ecole',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="École d'affectation"
    )
    province_affectation = models.ForeignKey(
        'ecoles.Province',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='users',
        verbose_name="Province d'affectation"
    )
    niveau_affectation = models.ForeignKey(
        'ecoles.Niveau',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='enseignants',
        verbose_name="Niveau d'affectation"
    )
    classe_affectation = models.ForeignKey(
        'ecoles.Classe',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='enseignants',
        verbose_name="Classe d'affectation"
    )
    # Le champ eleves_associes a été SUPPRIMÉ
    date_creation = models.DateTimeField(auto_now_add=True)
    date_modification = models.DateTimeField(auto_now=True)
    est_actif = models.BooleanField(default=True)
    
    reset_code = models.CharField(max_length=6, null=True, blank=True)
    reset_code_created_at = models.DateTimeField(null=True, blank=True)
    reset_code_used = models.BooleanField(default=False)

    class Meta:
        ordering = ['-date_creation']

    def __str__(self):
        return f"{self.nom} {self.prenom} ({self.get_role_display()})"

    def get_full_name(self):
        return f"{self.nom} {self.postnom} {self.prenom}".strip()

    def est_administrateur(self): return self.role == self.Role.ADMIN
    def est_inspecteur(self): return self.role == self.Role.INSPECTEUR
    def est_agent(self): return self.role == self.Role.AGENT
    def est_enseignant(self): return self.role == self.Role.ENSEIGNANT
    def est_parent(self): return self.role == self.Role.PARENT
    def est_proved(self): return self.role == self.Role.PROVED
    
    def generate_reset_code(self):
        import random
        self.reset_code = ''.join(str(random.randint(0, 9)) for _ in range(6))
        self.reset_code_created_at = timezone.now()
        self.reset_code_used = False
        self.save()
        return self.reset_code
    
    def verify_reset_code(self, code):
        if self.reset_code_used:
            return False
        if self.reset_code != code:
            return False
        if self.reset_code_created_at:
            expiry = self.reset_code_created_at + timezone.timedelta(minutes=15)
            if timezone.now() > expiry:
                return False
        return True


class AuditLog(models.Model):
    class ActionType(models.TextChoices):
        LOGIN = 'LOGIN', 'Connexion'
        LOGOUT = 'LOGOUT', 'Déconnexion'
        CREATE = 'CREATE', 'Création'
        UPDATE = 'UPDATE', 'Modification'
        DELETE = 'DELETE', 'Suppression'
        VIEW = 'VIEW', 'Consultation'
        EXPORT = 'EXPORT', 'Export'
        IMPORT = 'IMPORT', 'Import'
        PASSWORD_RESET = 'PASSWORD_RESET', 'Réinitialisation mot de passe'
        PASSWORD_CHANGE = 'PASSWORD_CHANGE', 'Changement mot de passe'
        LOGIN_FAILED = 'LOGIN_FAILED', 'Échec de connexion'
    
    class ModelName(models.TextChoices):
        UTILISATEUR = 'Utilisateur', 'Utilisateur'
        ECOLE = 'Ecole', 'École'
        PROVINCE = 'Province', 'Province'
        NIVEAU = 'Niveau', 'Niveau'
        CLASSE = 'Classe', 'Classe'
        DOMAINE = 'Domaine', 'Domaine'
        COURS = 'Cours', 'Cours'
        ELEVE = 'Eleve', 'Élève'
        EVALUATION = 'EvaluationResultat', 'Résultat d\'évaluation'
        BULLETIN = 'Bulletin', 'Bulletin'
        ANNEE_SCOLAIRE = 'AnneeScolaire', 'Année scolaire'
    
    utilisateur = models.ForeignKey(Utilisateur, on_delete=models.SET_NULL, null=True, related_name='audit_logs')
    action = models.CharField(max_length=20, choices=ActionType.choices)
    model_name = models.CharField(max_length=50, choices=ModelName.choices, blank=True, null=True)
    object_id = models.CharField(max_length=50, blank=True, null=True)
    object_repr = models.CharField(max_length=200, blank=True, null=True)
    changes = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True, null=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    success = models.BooleanField(default=True)
    message = models.TextField(blank=True, null=True)
    
    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['utilisateur', 'timestamp']),
            models.Index(fields=['action', 'timestamp']),
            models.Index(fields=['model_name', 'object_id']),
        ]
    
    def __str__(self):
        return f"{self.get_action_display()} - {self.utilisateur} - {self.timestamp.strftime('%d/%m/%Y %H:%M')}"