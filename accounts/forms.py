from django import forms
from django.contrib.auth.forms import UserCreationForm, UserChangeForm
from .models import Utilisateur
from ecoles.models import Ecole, Niveau, Classe, Province


# ===================== FORMULAIRE DE CRÉATION =====================

class UtilisateurCreationForm(UserCreationForm):
    class Meta:
        model = Utilisateur
        fields = ('username', 'nom', 'postnom', 'prenom', 'email', 'role',
                  'ecole_affectation', 'province_affectation',
                  'niveau_affectation', 'classe_affectation')
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nom d\'utilisateur'}),
            'nom': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nom'}),
            'postnom': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Postnom (facultatif)'}),
            'prenom': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Prénom'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'email@exemple.com'}),
            'role': forms.Select(attrs={'class': 'form-select', 'id': 'id_role'}),
            'ecole_affectation': forms.Select(attrs={'class': 'form-select', 'id': 'id_ecole_affectation'}),
            'province_affectation': forms.Select(attrs={'class': 'form-select', 'id': 'id_province_affectation'}),
            'niveau_affectation': forms.Select(attrs={'class': 'form-select', 'id': 'id_niveau_affectation'}),
            'classe_affectation': forms.Select(attrs={'class': 'form-select', 'id': 'id_classe_affectation'}),
        }

    def __init__(self, *args, **kwargs):
        self.request_user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        # Champs optionnels (l'affectation dépend du rôle)
        self.fields['ecole_affectation'].required = False
        self.fields['province_affectation'].required = False
        self.fields['niveau_affectation'].required = False
        self.fields['classe_affectation'].required = False

        # Empty labels plus clairs
        self.fields['ecole_affectation'].empty_label = "— Aucune école —"
        self.fields['province_affectation'].empty_label = "— Aucune province —"
        self.fields['niveau_affectation'].empty_label = "— Aucun niveau —"
        self.fields['classe_affectation'].empty_label = "— Aucune classe —"

        # Le Ministre n'a jamais le droit de créer des utilisateurs (contrôlé par la vue),
        # mais on garde la logique défensive.
        if self.request_user and self.request_user.est_ministre():
            self.fields['ecole_affectation'].queryset = Ecole.objects.none()
            self.fields['province_affectation'].queryset = Province.objects.none()
            self.fields['niveau_affectation'].queryset = Niveau.objects.none()
            self.fields['classe_affectation'].queryset = Classe.objects.none()
            return

        # ---------- Niveaux et classes déjà affectés à exclure ----------
        # (pour éviter de proposer des valeurs qui seront refusées)
        niveaux_pris = Utilisateur.objects.exclude(
            niveau_affectation__isnull=True
        ).values_list('niveau_affectation_id', flat=True)

        classes_prises = Utilisateur.objects.exclude(
            classe_affectation__isnull=True
        ).values_list('classe_affectation_id', flat=True)

        if self.request_user:
            if self.request_user.est_proved():
                province = self.request_user.province_affectation
                if province:
                    self.fields['ecole_affectation'].queryset = Ecole.objects.filter(province=province)
                    self.fields['province_affectation'].queryset = Province.objects.filter(id=province.id)
                    self.fields['niveau_affectation'].queryset = Niveau.objects.filter(
                        ecole__province=province,
                        est_reference=False,
                    ).exclude(id__in=niveaux_pris)
                    self.fields['classe_affectation'].queryset = Classe.objects.filter(
                        ecole__province=province,
                        est_reference=False,
                    ).exclude(id__in=classes_prises)
                else:
                    self.fields['ecole_affectation'].queryset = Ecole.objects.none()
                    self.fields['province_affectation'].queryset = Province.objects.none()
                    self.fields['niveau_affectation'].queryset = Niveau.objects.none()
                    self.fields['classe_affectation'].queryset = Classe.objects.none()

            elif self.request_user.est_agent() or self.request_user.est_inspecteur():
                ecole = self.request_user.ecole_affectation
                if ecole:
                    self.fields['ecole_affectation'].queryset = Ecole.objects.filter(id=ecole.id)
                    self.fields['province_affectation'].queryset = Province.objects.filter(id=ecole.province.id)
                    self.fields['niveau_affectation'].queryset = Niveau.objects.filter(
                        ecole=ecole, est_reference=False
                    ).exclude(id__in=niveaux_pris)
                    self.fields['classe_affectation'].queryset = Classe.objects.filter(
                        ecole=ecole, est_reference=False
                    ).exclude(id__in=classes_prises)
                else:
                    # ✅ CORRECTION : si l'agent n'a pas d'école, il peut quand même
                    # affecter un nouvel utilisateur à n'importe quelle école
                    # (car il gère les références au niveau global).
                    if self.request_user.est_agent():
                        self.fields['ecole_affectation'].queryset = Ecole.objects.all()
                        self.fields['province_affectation'].queryset = Province.objects.all()
                        self.fields['niveau_affectation'].queryset = Niveau.objects.filter(
                            est_reference=False
                        ).exclude(id__in=niveaux_pris)
                        self.fields['classe_affectation'].queryset = Classe.objects.filter(
                            est_reference=False
                        ).exclude(id__in=classes_prises)
                    else:
                        self.fields['ecole_affectation'].queryset = Ecole.objects.none()
                        self.fields['province_affectation'].queryset = Province.objects.none()
                        self.fields['niveau_affectation'].queryset = Niveau.objects.none()
                        self.fields['classe_affectation'].queryset = Classe.objects.none()

            else:
                # Admin
                self.fields['ecole_affectation'].queryset = Ecole.objects.all()
                self.fields['province_affectation'].queryset = Province.objects.all()
                self.fields['niveau_affectation'].queryset = Niveau.objects.filter(
                    est_reference=False
                ).exclude(id__in=niveaux_pris)
                self.fields['classe_affectation'].queryset = Classe.objects.filter(
                    est_reference=False
                ).exclude(id__in=classes_prises)

    def clean_username(self):
        username = self.cleaned_data.get('username', '').strip()
        if Utilisateur.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError(
                f"Un utilisateur avec le nom d'utilisateur « {username} » existe déjà."
            )
        return username

    def clean_email(self):
        email = self.cleaned_data.get('email', '').strip()
        if not email:
            return email
        if Utilisateur.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(
                f"Un utilisateur avec l'email « {email} » existe déjà."
            )
        return email

    def clean_niveau_affectation(self):
        """Vérifie qu'aucun autre utilisateur n'a déjà ce niveau."""
        niveau = self.cleaned_data.get('niveau_affectation')
        if not niveau:
            return niveau

        existing = Utilisateur.objects.filter(niveau_affectation=niveau)
        if existing.exists():
            other = existing.first()
            raise forms.ValidationError(
                f"Le niveau « {niveau.nom} » est déjà affecté à "
                f"l'utilisateur « {other.get_full_name() or other.username} ». "
                f"Un niveau ne peut être affecté qu'à un seul utilisateur."
            )
        return niveau

    def clean_classe_affectation(self):
        """Vérifie qu'aucun autre utilisateur n'a déjà cette classe."""
        classe = self.cleaned_data.get('classe_affectation')
        if not classe:
            return classe

        existing = Utilisateur.objects.filter(classe_affectation=classe)
        if existing.exists():
            other = existing.first()
            raise forms.ValidationError(
                f"La classe « {classe.nom} » est déjà affectée à "
                f"l'utilisateur « {other.get_full_name() or other.username} ». "
                f"Une classe ne peut être affectée qu'à un seul utilisateur."
            )
        return classe

    def clean(self):
        cleaned_data = super().clean()

        role = cleaned_data.get('role')
        ecole = cleaned_data.get('ecole_affectation')
        province = cleaned_data.get('province_affectation')
        niveau = cleaned_data.get('niveau_affectation')
        classe = cleaned_data.get('classe_affectation')

        # ---------- Règles de cohérence école / niveau / classe ----------
        if niveau and ecole and niveau.ecole != ecole:
            self.add_error(
                'niveau_affectation',
                f"Le niveau « {niveau.nom} » n'appartient pas à l'école "
                f"« {ecole.nom} »."
            )
        if classe and ecole and classe.ecole != ecole:
            self.add_error(
                'classe_affectation',
                f"La classe « {classe.nom} » n'appartient pas à l'école "
                f"« {ecole.nom} »."
            )
        if classe and niveau and classe.niveau != niveau:
            self.add_error(
                'classe_affectation',
                f"La classe « {classe.nom} » n'appartient pas au niveau "
                f"« {niveau.nom} »."
            )

        # ---------- Règles par rôle ----------
        if role == Utilisateur.Role.ENSEIGNANT:
            if not classe:
                self.add_error('classe_affectation', "Un enseignant doit être affecté à une classe.")

        if role == Utilisateur.Role.PROVED:
            if not province:
                self.add_error('province_affectation', "Un Directeur Provincial doit être affecté à une province.")

        # ✅ CORRECTION : Seul l'INSPECTEUR doit être rattaché à une école.
        # L'AGENT est un rôle global (gestion des références : classes, cours,
        # niveaux, sections, etc.). L'école est donc FACULTATIVE pour lui.
        if role == Utilisateur.Role.INSPECTEUR:
            if not ecole:
                self.add_error('ecole_affectation', "Un inspecteur doit être affecté à une école.")

        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data['password1'])
        if commit:
            user.save()
        return user


# ===================== FORMULAIRE DE MODIFICATION =====================

class UtilisateurChangeForm(UserChangeForm):
    password = forms.CharField(
        label="Mot de passe",
        widget=forms.PasswordInput(attrs={'class': 'form-control'}),
        required=False,
        help_text="Laissez vide pour ne pas changer."
    )

    class Meta:
        model = Utilisateur
        fields = ('username', 'nom', 'postnom', 'prenom', 'email', 'role',
                  'ecole_affectation', 'province_affectation',
                  'niveau_affectation', 'classe_affectation', 'est_actif')
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control'}),
            'nom': forms.TextInput(attrs={'class': 'form-control'}),
            'postnom': forms.TextInput(attrs={'class': 'form-control'}),
            'prenom': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'role': forms.Select(attrs={'class': 'form-select', 'id': 'id_role'}),
            'ecole_affectation': forms.Select(attrs={'class': 'form-select', 'id': 'id_ecole_affectation'}),
            'province_affectation': forms.Select(attrs={'class': 'form-select', 'id': 'id_province_affectation'}),
            'niveau_affectation': forms.Select(attrs={'class': 'form-select', 'id': 'id_niveau_affectation'}),
            'classe_affectation': forms.Select(attrs={'class': 'form-select', 'id': 'id_classe_affectation'}),
            'est_actif': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        self.request_user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        # Champs optionnels
        self.fields['ecole_affectation'].required = False
        self.fields['province_affectation'].required = False
        self.fields['niveau_affectation'].required = False
        self.fields['classe_affectation'].required = False

        # Empty labels
        self.fields['ecole_affectation'].empty_label = "— Aucune école —"
        self.fields['province_affectation'].empty_label = "— Aucune province —"
        self.fields['niveau_affectation'].empty_label = "— Aucun niveau —"
        self.fields['classe_affectation'].empty_label = "— Aucune classe —"

        # Ministre : lecture seule
        if self.request_user and self.request_user.est_ministre():
            for field in self.fields.values():
                field.disabled = True
            return

        # ---------- Exclure les niveaux/classes déjà utilisés (sauf par soi-même) ----------
        qs_users = Utilisateur.objects.all()
        if self.instance and self.instance.pk:
            qs_users = qs_users.exclude(pk=self.instance.pk)

        niveaux_pris = qs_users.exclude(
            niveau_affectation__isnull=True
        ).values_list('niveau_affectation_id', flat=True)

        classes_prises = qs_users.exclude(
            classe_affectation__isnull=True
        ).values_list('classe_affectation_id', flat=True)

        # ---------- Filtrage selon le rôle du demandeur ----------
        if self.request_user:
            if self.request_user.est_proved():
                province = self.request_user.province_affectation
                if province:
                    self.fields['ecole_affectation'].queryset = Ecole.objects.filter(province=province)
                    self.fields['province_affectation'].queryset = Province.objects.filter(id=province.id)
                    self.fields['niveau_affectation'].queryset = Niveau.objects.filter(
                        ecole__province=province,
                        est_reference=False,
                    ).exclude(id__in=niveaux_pris)
                    self.fields['classe_affectation'].queryset = Classe.objects.filter(
                        ecole__province=province,
                        est_reference=False,
                    ).exclude(id__in=classes_prises)
                else:
                    self.fields['ecole_affectation'].queryset = Ecole.objects.none()
                    self.fields['province_affectation'].queryset = Province.objects.none()
                    self.fields['niveau_affectation'].queryset = Niveau.objects.none()
                    self.fields['classe_affectation'].queryset = Classe.objects.none()

            elif self.request_user.est_agent() or self.request_user.est_inspecteur():
                ecole = self.request_user.ecole_affectation
                if ecole:
                    self.fields['ecole_affectation'].queryset = Ecole.objects.filter(id=ecole.id)
                    self.fields['province_affectation'].queryset = Province.objects.filter(id=ecole.province.id)
                    self.fields['niveau_affectation'].queryset = Niveau.objects.filter(
                        ecole=ecole, est_reference=False
                    ).exclude(id__in=niveaux_pris)
                    self.fields['classe_affectation'].queryset = Classe.objects.filter(
                        ecole=ecole, est_reference=False
                    ).exclude(id__in=classes_prises)
                else:
                    # ✅ CORRECTION : si l'agent n'a pas d'école, il peut quand même
                    # modifier un utilisateur sur n'importe quelle école.
                    if self.request_user.est_agent():
                        self.fields['ecole_affectation'].queryset = Ecole.objects.all()
                        self.fields['province_affectation'].queryset = Province.objects.all()
                        self.fields['niveau_affectation'].queryset = Niveau.objects.filter(
                            est_reference=False
                        ).exclude(id__in=niveaux_pris)
                        self.fields['classe_affectation'].queryset = Classe.objects.filter(
                            est_reference=False
                        ).exclude(id__in=classes_prises)
                    else:
                        self.fields['ecole_affectation'].queryset = Ecole.objects.none()
                        self.fields['province_affectation'].queryset = Province.objects.none()
                        self.fields['niveau_affectation'].queryset = Niveau.objects.none()
                        self.fields['classe_affectation'].queryset = Classe.objects.none()

            else:
                # Admin
                self.fields['ecole_affectation'].queryset = Ecole.objects.all()
                self.fields['province_affectation'].queryset = Province.objects.all()
                self.fields['niveau_affectation'].queryset = Niveau.objects.filter(
                    est_reference=False
                ).exclude(id__in=niveaux_pris)
                self.fields['classe_affectation'].queryset = Classe.objects.filter(
                    est_reference=False
                ).exclude(id__in=classes_prises)

        # ---------- En édition : réintégrer la valeur actuelle de l'instance ----------
        # Sinon le champ ne pourrait pas afficher la valeur déjà sélectionnée.
        if self.instance and self.instance.pk:
            if self.instance.niveau_affectation_id:
                niveau_actuel = Niveau.objects.filter(pk=self.instance.niveau_affectation_id)
                self.fields['niveau_affectation'].queryset = (
                    self.fields['niveau_affectation'].queryset | niveau_actuel
                ).distinct()
            if self.instance.classe_affectation_id:
                classe_actuelle = Classe.objects.filter(pk=self.instance.classe_affectation_id)
                self.fields['classe_affectation'].queryset = (
                    self.fields['classe_affectation'].queryset | classe_actuelle
                ).distinct()
            if self.instance.ecole_affectation_id:
                ecole_actuelle = Ecole.objects.filter(pk=self.instance.ecole_affectation_id)
                self.fields['ecole_affectation'].queryset = (
                    self.fields['ecole_affectation'].queryset | ecole_actuelle
                ).distinct()
            if self.instance.province_affectation_id:
                province_actuelle = Province.objects.filter(pk=self.instance.province_affectation_id)
                self.fields['province_affectation'].queryset = (
                    self.fields['province_affectation'].queryset | province_actuelle
                ).distinct()

    def clean_username(self):
        username = self.cleaned_data.get('username', '').strip()
        qs = Utilisateur.objects.filter(username__iexact=username)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError(
                f"Un utilisateur avec le nom d'utilisateur « {username} » existe déjà."
            )
        return username

    def clean_email(self):
        email = self.cleaned_data.get('email', '').strip()
        if not email:
            return email
        qs = Utilisateur.objects.filter(email__iexact=email)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError(
                f"Un utilisateur avec l'email « {email} » existe déjà."
            )
        return email

    def clean_niveau_affectation(self):
        """Vérifie qu'aucun autre utilisateur n'a déjà ce niveau."""
        niveau = self.cleaned_data.get('niveau_affectation')
        if not niveau:
            return niveau

        qs = Utilisateur.objects.filter(niveau_affectation=niveau)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)

        if qs.exists():
            other = qs.first()
            raise forms.ValidationError(
                f"Le niveau « {niveau.nom} » est déjà affecté à "
                f"l'utilisateur « {other.get_full_name() or other.username} ». "
                f"Un niveau ne peut être affecté qu'à un seul utilisateur."
            )
        return niveau

    def clean_classe_affectation(self):
        """Vérifie qu'aucun autre utilisateur n'a déjà cette classe."""
        classe = self.cleaned_data.get('classe_affectation')
        if not classe:
            return classe

        qs = Utilisateur.objects.filter(classe_affectation=classe)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)

        if qs.exists():
            other = qs.first()
            raise forms.ValidationError(
                f"La classe « {classe.nom} » est déjà affectée à "
                f"l'utilisateur « {other.get_full_name() or other.username} ». "
                f"Une classe ne peut être affectée qu'à un seul utilisateur."
            )
        return classe

    def clean(self):
        cleaned_data = super().clean()

        role = cleaned_data.get('role')
        ecole = cleaned_data.get('ecole_affectation')
        province = cleaned_data.get('province_affectation')
        niveau = cleaned_data.get('niveau_affectation')
        classe = cleaned_data.get('classe_affectation')

        # ---------- Règles de cohérence école / niveau / classe ----------
        if niveau and ecole and niveau.ecole != ecole:
            self.add_error(
                'niveau_affectation',
                f"Le niveau « {niveau.nom} » n'appartient pas à l'école "
                f"« {ecole.nom} »."
            )
        if classe and ecole and classe.ecole != ecole:
            self.add_error(
                'classe_affectation',
                f"La classe « {classe.nom} » n'appartient pas à l'école "
                f"« {ecole.nom} »."
            )
        if classe and niveau and classe.niveau != niveau:
            self.add_error(
                'classe_affectation',
                f"La classe « {classe.nom} » n'appartient pas au niveau "
                f"« {niveau.nom} »."
            )

        # ---------- Règles par rôle ----------
        if role == Utilisateur.Role.ENSEIGNANT:
            if not classe:
                self.add_error('classe_affectation', "Un enseignant doit être affecté à une classe.")

        if role == Utilisateur.Role.PROVED:
            if not province:
                self.add_error('province_affectation', "Un Directeur Provincial doit être affecté à une province.")

        # ✅ CORRECTION : Seul l'INSPECTEUR doit être rattaché à une école.
        # L'AGENT est un rôle global : école FACULTATIVE.
        if role == Utilisateur.Role.INSPECTEUR:
            if not ecole:
                self.add_error('ecole_affectation', "Un inspecteur doit être affecté à une école.")

        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        password = self.cleaned_data.get('password')
        if password:
            user.set_password(password)
        if commit:
            user.save()
        return user


# ===================== FORMULAIRES MOT DE PASSE =====================

class PasswordResetRequestForm(forms.Form):
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'exemple@email.com'})
    )


class PasswordResetVerifyForm(forms.Form):
    code = forms.CharField(
        max_length=6,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '123456'})
    )
    new_password = forms.CharField(
        min_length=8,
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Nouveau mot de passe'})
    )
    confirm_password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Confirmer'})
    )

    def clean(self):
        cleaned_data = super().clean()
        new = cleaned_data.get('new_password')
        confirm = cleaned_data.get('confirm_password')
        if new and confirm and new != confirm:
            raise forms.ValidationError("Les mots de passe ne correspondent pas.")
        return cleaned_data