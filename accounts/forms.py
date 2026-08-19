from django import forms
from django.contrib.auth.forms import UserCreationForm, UserChangeForm
from .models import Utilisateur
from ecoles.models import Ecole, Niveau, Classe, Province

class UtilisateurCreationForm(UserCreationForm):
    class Meta:
        model = Utilisateur
        fields = ('username', 'nom', 'postnom', 'prenom', 'email', 'role',
                  'ecole_affectation', 'province_affectation', 'niveau_affectation', 'classe_affectation')
        widgets = {
            'nom': forms.TextInput(attrs={'class': 'form-control'}),
            'postnom': forms.TextInput(attrs={'class': 'form-control'}),
            'prenom': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'role': forms.Select(attrs={'class': 'form-select'}),
            'ecole_affectation': forms.Select(attrs={'class': 'form-select'}),
            'province_affectation': forms.Select(attrs={'class': 'form-select'}),
            'niveau_affectation': forms.Select(attrs={'class': 'form-select'}),
            'classe_affectation': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, **kwargs):
        self.request_user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        # Filtrer les choix en fonction du rôle de l'utilisateur connecté
        if self.request_user:
            if self.request_user.est_proved():
                # Un proved ne peut créer que des utilisateurs pour sa province
                province = self.request_user.province_affectation
                if province:
                    self.fields['ecole_affectation'].queryset = Ecole.objects.filter(province=province)
                    self.fields['province_affectation'].queryset = Province.objects.filter(id=province.id)
                else:
                    self.fields['ecole_affectation'].queryset = Ecole.objects.none()
                    self.fields['province_affectation'].queryset = Province.objects.none()
            elif self.request_user.est_agent() or self.request_user.est_inspecteur():
                ecole = self.request_user.ecole_affectation
                if ecole:
                    self.fields['ecole_affectation'].queryset = Ecole.objects.filter(id=ecole.id)
                    self.fields['province_affectation'].queryset = Province.objects.filter(id=ecole.province.id)
                    self.fields['niveau_affectation'].queryset = Niveau.objects.filter(ecole=ecole)
                    self.fields['classe_affectation'].queryset = Classe.objects.filter(ecole=ecole)
                else:
                    self.fields['ecole_affectation'].queryset = Ecole.objects.none()
                    self.fields['province_affectation'].queryset = Province.objects.none()
                    self.fields['niveau_affectation'].queryset = Niveau.objects.none()
                    self.fields['classe_affectation'].queryset = Classe.objects.none()
            else:
                # Admin
                self.fields['ecole_affectation'].queryset = Ecole.objects.all()
                self.fields['province_affectation'].queryset = Province.objects.all()
                self.fields['niveau_affectation'].queryset = Niveau.objects.all()
                self.fields['classe_affectation'].queryset = Classe.objects.all()

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data['password1'])
        if commit:
            user.save()
        return user


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
                  'ecole_affectation', 'province_affectation', 'niveau_affectation', 'classe_affectation', 'est_actif')
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control'}),
            'nom': forms.TextInput(attrs={'class': 'form-control'}),
            'postnom': forms.TextInput(attrs={'class': 'form-control'}),
            'prenom': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'role': forms.Select(attrs={'class': 'form-select'}),
            'ecole_affectation': forms.Select(attrs={'class': 'form-select'}),
            'province_affectation': forms.Select(attrs={'class': 'form-select'}),
            'niveau_affectation': forms.Select(attrs={'class': 'form-select'}),
            'classe_affectation': forms.Select(attrs={'class': 'form-select'}),
            'est_actif': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        self.request_user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        # Mêmes filtres que pour la création
        if self.request_user:
            if self.request_user.est_proved():
                province = self.request_user.province_affectation
                if province:
                    self.fields['ecole_affectation'].queryset = Ecole.objects.filter(province=province)
                    self.fields['province_affectation'].queryset = Province.objects.filter(id=province.id)
                else:
                    self.fields['ecole_affectation'].queryset = Ecole.objects.none()
                    self.fields['province_affectation'].queryset = Province.objects.none()
            elif self.request_user.est_agent() or self.request_user.est_inspecteur():
                ecole = self.request_user.ecole_affectation
                if ecole:
                    self.fields['ecole_affectation'].queryset = Ecole.objects.filter(id=ecole.id)
                    self.fields['province_affectation'].queryset = Province.objects.filter(id=ecole.province.id)
                    self.fields['niveau_affectation'].queryset = Niveau.objects.filter(ecole=ecole)
                    self.fields['classe_affectation'].queryset = Classe.objects.filter(ecole=ecole)
                else:
                    self.fields['ecole_affectation'].queryset = Ecole.objects.none()
                    self.fields['province_affectation'].queryset = Province.objects.none()
                    self.fields['niveau_affectation'].queryset = Niveau.objects.none()
                    self.fields['classe_affectation'].queryset = Classe.objects.none()
            else:
                self.fields['ecole_affectation'].queryset = Ecole.objects.all()
                self.fields['province_affectation'].queryset = Province.objects.all()
                self.fields['niveau_affectation'].queryset = Niveau.objects.all()
                self.fields['classe_affectation'].queryset = Classe.objects.all()

    def save(self, commit=True):
        user = super().save(commit=False)
        password = self.cleaned_data.get('password')
        if password:
            user.set_password(password)
        if commit:
            user.save()
        return user


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