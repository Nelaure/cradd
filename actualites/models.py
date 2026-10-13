from django.db import models
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils.text import slugify

User = get_user_model()


class Categorie(models.Model):
    nom = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True)
    description = models.TextField(blank=True)

    class Meta:
        verbose_name = "Catégorie"
        verbose_name_plural = "Catégories"
        ordering = ['nom']

    def __str__(self):
        return self.nom

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.nom)
        super().save(*args, **kwargs)


class Article(models.Model):
    class Statut(models.TextChoices):
        BROUILLON = 'BROUILLON', 'Brouillon'
        PUBLIE = 'PUBLIE', 'Publié'
        ARCHIVE = 'ARCHIVE', 'Archivé'

    titre = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200, unique=True)
    contenu = models.TextField()
    image = models.ImageField(upload_to='articles/', blank=True, null=True)
    categorie = models.ForeignKey(Categorie, on_delete=models.SET_NULL, null=True, blank=True, related_name='articles')
    auteur = models.ForeignKey(User, on_delete=models.CASCADE, related_name='articles')
    statut = models.CharField(max_length=20, choices=Statut.choices, default=Statut.BROUILLON)
    date_creation = models.DateTimeField(auto_now_add=True)
    date_modification = models.DateTimeField(auto_now=True)
    date_publication = models.DateTimeField(null=True, blank=True)
    est_visible = models.BooleanField(default=True)
    deleted_at = models.DateTimeField(null=True, blank=True)  # <-- Soft delete

    class Meta:
        ordering = ['-date_publication', '-date_creation']
        indexes = [
            models.Index(fields=['statut', 'est_visible']),
            models.Index(fields=['date_publication']),
        ]

    def __str__(self):
        return self.titre

    def get_absolute_url(self):
        return reverse('actualites:article_detail', kwargs={'slug': self.slug})

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.titre)
        if self.statut == self.Statut.PUBLIE and not self.date_publication:
            self.date_publication = timezone.now()
        super().save(*args, **kwargs)

    # ----- Soft delete -----
    def delete(self, using=None, keep_parents=False):
        """Marque l'article comme supprimé (soft delete) au lieu de le supprimer réellement."""
        self.deleted_at = timezone.now()
        self.save()

    def hard_delete(self):
        """Supprime définitivement l'article."""
        super().delete()

    def restore(self):
        """Restaure l'article (annule le soft delete)."""
        self.deleted_at = None
        self.save()

    @classmethod
    def all_objects(cls):
        """Retourne tous les articles, y compris ceux dans la corbeille."""
        return cls.objects.all()

    @classmethod
    def active_objects(cls):
        """Retourne les articles non supprimés."""
        return cls.objects.filter(deleted_at__isnull=True)