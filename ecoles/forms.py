from django import forms
from django.forms import inlineformset_factory
from .models import (
    Ecole, Niveau, Classe, Domaine, Cours, AnneeScolaire,
    CycleEvaluation, EvaluationConfig, EvaluationResultat, Province
)
from eleves.models import Eleve
from accounts.models import Utilisateur

# ===================== FORMULAIRES AVEC FILTRAGE PAR RÔLE =====================

class ProvinceForm(forms.ModelForm):
    class Meta:
        model = Province
        fields = ['nom', 'code', 'description']
        widgets = {
            'nom': forms.TextInput(attrs={'class': 'form-control'}),
            'code': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

class EcoleForm(forms.ModelForm):
    niveaux_reference = forms.ModelMultipleChoiceField(
        queryset=Niveau.objects.filter(est_reference=True, ecole__isnull=True),
        required=False,
        label="Niveaux de référence à affecter",
        widget=forms.SelectMultiple(attrs={'class': 'form-select'})
    )
    province = forms.ModelChoiceField(
        queryset=Province.objects.all(),
        label="Province",
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    type_gestion = forms.ChoiceField(
        choices=Ecole.TYPE_GESTION_CHOICES,
        label="Type de gestion",
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    class Meta:
        model = Ecole
        fields = ['nom', 'code', 'province', 'type_gestion', 'responsable', 'contact', 'adresse', 'telephone', 'email', 'est_active']
        widgets = {
            'nom': forms.TextInput(attrs={'class': 'form-control'}),
            'code': forms.TextInput(attrs={'class': 'form-control'}),
            'responsable': forms.TextInput(attrs={'class': 'form-control'}),
            'contact': forms.TextInput(attrs={'class': 'form-control'}),
            'adresse': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'telephone': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'est_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        if self.user:
            if self.user.est_agent() or self.user.est_inspecteur() or self.user.est_proved():
                self.fields['province'].disabled = True
                if self.user.est_proved() and self.user.province_affectation:
                    self.fields['province'].initial = self.user.province_affectation.id
                    self.fields['province'].queryset = Province.objects.filter(id=self.user.province_affectation.id)
                elif self.user.est_agent() and self.user.ecole_affectation:
                    self.fields['province'].initial = self.user.ecole_affectation.province.id
                    self.fields['province'].queryset = Province.objects.filter(id=self.user.ecole_affectation.province.id)

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.user and self.user.est_proved() and self.user.province_affectation:
            instance.province = self.user.province_affectation
        if commit:
            instance.save()
            self.save_m2m()
        return instance


class NiveauForm(forms.ModelForm):
    class Meta:
        model = Niveau
        fields = ['nom', 'description', 'ordre', 'ecole', 'est_reference']
        widgets = {
            'nom': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'ordre': forms.NumberInput(attrs={'class': 'form-control'}),
            'ecole': forms.Select(attrs={'class': 'form-select'}),
            'est_reference': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        self.is_reference = kwargs.pop('is_reference', False)
        super().__init__(*args, **kwargs)

        if self.is_reference:
            self.fields['ecole'].queryset = Ecole.objects.none()
            self.fields['ecole'].widget = forms.HiddenInput()
            self.fields['ecole'].required = False
            self.fields['est_reference'].initial = True
            self.fields['est_reference'].disabled = True
        else:
            if self.user:
                if self.user.est_enseignant():
                    for field in self.fields:
                        self.fields[field].disabled = True
                elif self.user.est_agent() or self.user.est_inspecteur():
                    if self.user.ecole_affectation:
                        self.fields['ecole'].queryset = Ecole.objects.filter(id=self.user.ecole_affectation.id)
                        self.fields['ecole'].initial = self.user.ecole_affectation.id
                        self.fields['ecole'].disabled = True
                    else:
                        self.fields['ecole'].queryset = Ecole.objects.none()
                elif self.user.est_proved():
                    self.fields['ecole'].queryset = Ecole.objects.filter(province=self.user.province_affectation) if self.user.province_affectation else Ecole.objects.none()
                    if self.instance.pk and self.instance.ecole:
                        self.fields['ecole'].initial = self.instance.ecole.id
                        self.fields['ecole'].disabled = True
                    else:
                        self.fields['ecole'].disabled = True
                else:
                    self.fields['ecole'].queryset = Ecole.objects.all()

    def clean(self):
        cleaned_data = super().clean()
        if self.is_reference:
            cleaned_data['ecole'] = None
            cleaned_data['est_reference'] = True
        else:
            if self.user and (self.user.est_agent() or self.user.est_inspecteur()):
                if self.user.ecole_affectation:
                    cleaned_data['ecole'] = self.user.ecole_affectation
                else:
                    raise forms.ValidationError("Vous devez être affecté à une école.")
            elif self.user and self.user.est_proved():
                if self.user.province_affectation:
                    ecole = cleaned_data.get('ecole')
                    if ecole and ecole.province != self.user.province_affectation:
                        raise forms.ValidationError("L'école choisie n'appartient pas à votre province.")
                else:
                    raise forms.ValidationError("Vous n'êtes pas affecté à une province.")
        return cleaned_data


class ClasseForm(forms.ModelForm):
    class Meta:
        model = Classe
        fields = ['nom', 'description', 'ordre', 'niveau', 'ecole', 'est_reference']
        widgets = {
            'nom': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'ordre': forms.NumberInput(attrs={'class': 'form-control'}),
            'niveau': forms.Select(attrs={'class': 'form-select'}),
            'ecole': forms.Select(attrs={'class': 'form-select'}),
            'est_reference': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        self.is_reference = kwargs.pop('is_reference', False)
        super().__init__(*args, **kwargs)

        if self.is_reference:
            self.fields['ecole'].queryset = Ecole.objects.none()
            self.fields['ecole'].widget = forms.HiddenInput()
            self.fields['ecole'].required = False
            self.fields['est_reference'].initial = True
            self.fields['est_reference'].disabled = True
            self.fields['niveau'].queryset = Niveau.objects.filter(est_reference=True, ecole__isnull=True)
        else:
            if self.user:
                if self.user.est_enseignant():
                    for field in self.fields:
                        self.fields[field].disabled = True
                elif self.user.est_agent() or self.user.est_inspecteur():
                    if self.user.ecole_affectation:
                        self.fields['ecole'].queryset = Ecole.objects.filter(id=self.user.ecole_affectation.id)
                        self.fields['ecole'].initial = self.user.ecole_affectation.id
                        self.fields['ecole'].disabled = True
                        self.fields['niveau'].queryset = Niveau.objects.filter(ecole=self.user.ecole_affectation, est_reference=False)
                    else:
                        self.fields['ecole'].queryset = Ecole.objects.none()
                        self.fields['niveau'].queryset = Niveau.objects.none()
                elif self.user.est_proved():
                    if self.user.province_affectation:
                        ecoles = Ecole.objects.filter(province=self.user.province_affectation)
                        self.fields['ecole'].queryset = ecoles
                        if self.instance.pk and self.instance.ecole:
                            self.fields['ecole'].initial = self.instance.ecole.id
                            self.fields['ecole'].disabled = True
                        else:
                            self.fields['ecole'].disabled = True
                        self.fields['niveau'].queryset = Niveau.objects.filter(ecole__in=ecoles, est_reference=False)
                    else:
                        self.fields['ecole'].queryset = Ecole.objects.none()
                        self.fields['niveau'].queryset = Niveau.objects.none()
                else:
                    self.fields['ecole'].queryset = Ecole.objects.all()
                    self.fields['niveau'].queryset = Niveau.objects.filter(est_reference=False)

    def clean(self):
        cleaned_data = super().clean()
        if self.is_reference:
            cleaned_data['ecole'] = None
            cleaned_data['est_reference'] = True
        else:
            if self.user and (self.user.est_agent() or self.user.est_inspecteur()):
                if self.user.ecole_affectation:
                    cleaned_data['ecole'] = self.user.ecole_affectation
                else:
                    raise forms.ValidationError("Vous devez être affecté à une école.")
            elif self.user and self.user.est_proved():
                ecole = cleaned_data.get('ecole')
                if ecole and ecole.province != self.user.province_affectation:
                    raise forms.ValidationError("L'école choisie n'appartient pas à votre province.")
        return cleaned_data


class DomaineForm(forms.ModelForm):
    class Meta:
        model = Domaine
        fields = ['nom', 'description', 'ecole', 'est_reference', 'niveaux', 'classes']
        widgets = {
            'nom': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'ecole': forms.Select(attrs={'class': 'form-select'}),
            'est_reference': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'niveaux': forms.SelectMultiple(attrs={'class': 'form-select'}),
            'classes': forms.SelectMultiple(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        self.is_reference = kwargs.pop('is_reference', False)
        super().__init__(*args, **kwargs)

        if self.is_reference:
            self.fields['ecole'].queryset = Ecole.objects.none()
            self.fields['ecole'].widget = forms.HiddenInput()
            self.fields['ecole'].required = False
            self.fields['est_reference'].initial = True
            self.fields['est_reference'].disabled = True
            self.fields['niveaux'].queryset = Niveau.objects.filter(est_reference=True, ecole__isnull=True)
            self.fields['classes'].queryset = Classe.objects.filter(est_reference=True, ecole__isnull=True)
        else:
            if self.user:
                if self.user.est_enseignant():
                    for field in self.fields:
                        self.fields[field].disabled = True
                elif self.user.est_agent() or self.user.est_inspecteur():
                    if self.user.ecole_affectation:
                        self.fields['ecole'].queryset = Ecole.objects.filter(id=self.user.ecole_affectation.id)
                        self.fields['ecole'].initial = self.user.ecole_affectation.id
                        self.fields['ecole'].disabled = True
                        self.fields['niveaux'].queryset = Niveau.objects.filter(ecole=self.user.ecole_affectation, est_reference=False)
                        self.fields['classes'].queryset = Classe.objects.filter(ecole=self.user.ecole_affectation, est_reference=False)
                    else:
                        self.fields['ecole'].queryset = Ecole.objects.none()
                        self.fields['niveaux'].queryset = Niveau.objects.none()
                        self.fields['classes'].queryset = Classe.objects.none()
                elif self.user.est_proved():
                    if self.user.province_affectation:
                        ecoles = Ecole.objects.filter(province=self.user.province_affectation)
                        self.fields['ecole'].queryset = ecoles
                        if self.instance.pk and self.instance.ecole:
                            self.fields['ecole'].initial = self.instance.ecole.id
                            self.fields['ecole'].disabled = True
                        else:
                            self.fields['ecole'].disabled = True
                        self.fields['niveaux'].queryset = Niveau.objects.filter(ecole__in=ecoles, est_reference=False)
                        self.fields['classes'].queryset = Classe.objects.filter(ecole__in=ecoles, est_reference=False)
                    else:
                        self.fields['ecole'].queryset = Ecole.objects.none()
                        self.fields['niveaux'].queryset = Niveau.objects.none()
                        self.fields['classes'].queryset = Classe.objects.none()
                else:
                    self.fields['ecole'].queryset = Ecole.objects.all()
                    self.fields['niveaux'].queryset = Niveau.objects.filter(est_reference=False)
                    self.fields['classes'].queryset = Classe.objects.filter(est_reference=False)

    def clean(self):
        cleaned_data = super().clean()
        if self.is_reference:
            cleaned_data['ecole'] = None
            cleaned_data['est_reference'] = True
        else:
            if self.user and (self.user.est_agent() or self.user.est_inspecteur()):
                if self.user.ecole_affectation:
                    cleaned_data['ecole'] = self.user.ecole_affectation
                else:
                    raise forms.ValidationError("Vous devez être affecté à une école.")
            elif self.user and self.user.est_proved():
                ecole = cleaned_data.get('ecole')
                if ecole and ecole.province != self.user.province_affectation:
                    raise forms.ValidationError("L'école choisie n'appartient pas à votre province.")
        return cleaned_data


class CoursForm(forms.ModelForm):
    class Meta:
        model = Cours
        fields = ['nom', 'code', 'coefficient', 'description', 'niveau', 'classe', 'domaine', 'ecole', 'est_reference']
        widgets = {
            'nom': forms.TextInput(attrs={'class': 'form-control'}),
            'code': forms.TextInput(attrs={'class': 'form-control'}),
            'coefficient': forms.NumberInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'niveau': forms.Select(attrs={'class': 'form-select'}),
            'classe': forms.Select(attrs={'class': 'form-select'}),
            'domaine': forms.Select(attrs={'class': 'form-select'}),
            'ecole': forms.Select(attrs={'class': 'form-select'}),
            'est_reference': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        self.is_reference = kwargs.pop('is_reference', False)
        super().__init__(*args, **kwargs)

        if self.is_reference:
            self.fields['ecole'].queryset = Ecole.objects.none()
            self.fields['ecole'].widget = forms.HiddenInput()
            self.fields['ecole'].required = False
            self.fields['est_reference'].initial = True
            self.fields['est_reference'].disabled = True
            self.fields['niveau'].queryset = Niveau.objects.filter(est_reference=True, ecole__isnull=True)
            self.fields['classe'].queryset = Classe.objects.filter(est_reference=True, ecole__isnull=True)
            self.fields['domaine'].queryset = Domaine.objects.filter(est_reference=True, ecole__isnull=True)
        else:
            if self.user:
                if self.user.est_enseignant():
                    for field in self.fields:
                        self.fields[field].disabled = True
                    if self.user.classe_affectation:
                        self.fields['classe'].queryset = Classe.objects.filter(id=self.user.classe_affectation.id)
                        self.fields['classe'].initial = self.user.classe_affectation.id
                        self.fields['niveau'].queryset = Niveau.objects.filter(id=self.user.niveau_affectation.id) if self.user.niveau_affectation else Niveau.objects.none()
                        self.fields['domaine'].queryset = Domaine.objects.filter(ecole=self.user.ecole_affectation, est_reference=False)
                        self.fields['ecole'].queryset = Ecole.objects.filter(id=self.user.ecole_affectation.id)
                        self.fields['ecole'].disabled = True
                elif self.user.est_agent() or self.user.est_inspecteur():
                    if self.user.ecole_affectation:
                        self.fields['ecole'].queryset = Ecole.objects.filter(id=self.user.ecole_affectation.id)
                        self.fields['ecole'].initial = self.user.ecole_affectation.id
                        self.fields['ecole'].disabled = True
                        self.fields['niveau'].queryset = Niveau.objects.filter(ecole=self.user.ecole_affectation, est_reference=False)
                        self.fields['classe'].queryset = Classe.objects.filter(ecole=self.user.ecole_affectation, est_reference=False)
                        self.fields['domaine'].queryset = Domaine.objects.filter(ecole=self.user.ecole_affectation, est_reference=False)
                    else:
                        self.fields['ecole'].queryset = Ecole.objects.none()
                        self.fields['niveau'].queryset = Niveau.objects.none()
                        self.fields['classe'].queryset = Classe.objects.none()
                        self.fields['domaine'].queryset = Domaine.objects.none()
                elif self.user.est_proved():
                    if self.user.province_affectation:
                        ecoles = Ecole.objects.filter(province=self.user.province_affectation)
                        self.fields['ecole'].queryset = ecoles
                        if self.instance.pk and self.instance.ecole:
                            self.fields['ecole'].initial = self.instance.ecole.id
                            self.fields['ecole'].disabled = True
                        else:
                            self.fields['ecole'].disabled = True
                        self.fields['niveau'].queryset = Niveau.objects.filter(ecole__in=ecoles, est_reference=False)
                        self.fields['classe'].queryset = Classe.objects.filter(ecole__in=ecoles, est_reference=False)
                        self.fields['domaine'].queryset = Domaine.objects.filter(ecole__in=ecoles, est_reference=False)
                    else:
                        self.fields['ecole'].queryset = Ecole.objects.none()
                        self.fields['niveau'].queryset = Niveau.objects.none()
                        self.fields['classe'].queryset = Classe.objects.none()
                        self.fields['domaine'].queryset = Domaine.objects.none()
                else:
                    self.fields['ecole'].queryset = Ecole.objects.all()
                    self.fields['niveau'].queryset = Niveau.objects.filter(est_reference=False)
                    self.fields['classe'].queryset = Classe.objects.filter(est_reference=False)
                    self.fields['domaine'].queryset = Domaine.objects.filter(est_reference=False)

    def clean(self):
        cleaned_data = super().clean()
        if self.is_reference:
            cleaned_data['ecole'] = None
            cleaned_data['est_reference'] = True
        else:
            if self.user and (self.user.est_agent() or self.user.est_inspecteur()):
                if self.user.ecole_affectation:
                    cleaned_data['ecole'] = self.user.ecole_affectation
                else:
                    raise forms.ValidationError("Vous devez être affecté à une école.")
            if self.user and self.user.est_enseignant():
                if self.user.classe_affectation:
                    cleaned_data['classe'] = self.user.classe_affectation
                    cleaned_data['niveau'] = self.user.niveau_affectation
                    cleaned_data['ecole'] = self.user.ecole_affectation
                else:
                    raise forms.ValidationError("Vous devez être affecté à une classe.")
            elif self.user and self.user.est_proved():
                ecole = cleaned_data.get('ecole')
                if ecole and ecole.province != self.user.province_affectation:
                    raise forms.ValidationError("L'école choisie n'appartient pas à votre province.")
        return cleaned_data


class AnneeScolaireForm(forms.ModelForm):
    class Meta:
        model = AnneeScolaire
        fields = ['annee', 'date_debut', 'date_fin', 'est_actuelle', 'ecoles']
        widgets = {
            'annee': forms.TextInput(attrs={'class': 'form-control'}),
            'date_debut': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'date_fin': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'est_actuelle': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'ecoles': forms.SelectMultiple(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['ecoles'].queryset = Ecole.objects.all()


class CycleEvaluationForm(forms.ModelForm):
    class Meta:
        model = CycleEvaluation
        fields = ['type_cycle']
        widgets = {
            'type_cycle': forms.Select(attrs={'class': 'form-select'}),
        }


class EvaluationConfigForm(forms.ModelForm):
    class Meta:
        model = EvaluationConfig
        fields = ['cycle_num', 'periode_num', 'type', 'points_max', 'ordre']
        widgets = {
            'cycle_num': forms.NumberInput(attrs={'class': 'form-control'}),
            'periode_num': forms.NumberInput(attrs={'class': 'form-control'}),
            'type': forms.Select(attrs={'class': 'form-select'}),
            'points_max': forms.NumberInput(attrs={'class': 'form-control'}),
            'ordre': forms.NumberInput(attrs={'class': 'form-control'}),
        }


EvaluationConfigFormSet = inlineformset_factory(
    CycleEvaluation,
    EvaluationConfig,
    form=EvaluationConfigForm,
    extra=1,
    can_delete=True,
    min_num=0,
)


class ResultatSelectionForm(forms.Form):
    ecole = forms.ModelChoiceField(
        queryset=Ecole.objects.all(),
        required=False,
        label="École",
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    niveau = forms.ModelChoiceField(
        queryset=Niveau.objects.filter(est_reference=False),
        required=False,
        label="Niveau",
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    classe = forms.ModelChoiceField(
        queryset=Classe.objects.filter(est_reference=False),
        required=False,
        label="Classe",
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    eleve = forms.ModelChoiceField(
        queryset=Eleve.objects.all(),
        required=False,
        label="Élève",
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    cours = forms.ModelChoiceField(
        queryset=Cours.objects.filter(est_reference=False),
        required=False,
        label="Cours",
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    annee_scolaire = forms.ModelChoiceField(
        queryset=AnneeScolaire.objects.all(),
        required=False,
        label="Année scolaire",
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        if self.user:
            if self.user.est_enseignant():
                if self.user.ecole_affectation:
                    self.fields['ecole'].queryset = Ecole.objects.filter(id=self.user.ecole_affectation.id)
                    self.fields['ecole'].initial = self.user.ecole_affectation.id
                    self.fields['ecole'].disabled = True
                if self.user.niveau_affectation:
                    self.fields['niveau'].queryset = Niveau.objects.filter(id=self.user.niveau_affectation.id)
                    self.fields['niveau'].initial = self.user.niveau_affectation.id
                    self.fields['niveau'].disabled = True
                if self.user.classe_affectation:
                    self.fields['classe'].queryset = Classe.objects.filter(id=self.user.classe_affectation.id)
                    self.fields['classe'].initial = self.user.classe_affectation.id
                    self.fields['classe'].disabled = True
                    self.fields['eleve'].queryset = Eleve.objects.filter(classe=self.user.classe_affectation)
                    self.fields['cours'].queryset = Cours.objects.filter(classe=self.user.classe_affectation, est_reference=False)
                else:
                    self.fields['eleve'].queryset = Eleve.objects.none()
                    self.fields['cours'].queryset = Cours.objects.none()
            elif self.user.est_agent() or self.user.est_inspecteur():
                if self.user.ecole_affectation:
                    self.fields['ecole'].queryset = Ecole.objects.filter(id=self.user.ecole_affectation.id)
                    self.fields['ecole'].initial = self.user.ecole_affectation.id
                    self.fields['ecole'].disabled = True
                    self.fields['niveau'].queryset = Niveau.objects.filter(ecole=self.user.ecole_affectation, est_reference=False)
                    self.fields['classe'].queryset = Classe.objects.filter(ecole=self.user.ecole_affectation, est_reference=False)
                    self.fields['cours'].queryset = Cours.objects.filter(ecole=self.user.ecole_affectation, est_reference=False)
                    self.fields['eleve'].queryset = Eleve.objects.filter(ecole=self.user.ecole_affectation)
                else:
                    self.fields['ecole'].queryset = Ecole.objects.none()
                    self.fields['niveau'].queryset = Niveau.objects.none()
                    self.fields['classe'].queryset = Classe.objects.none()
                    self.fields['cours'].queryset = Cours.objects.none()
                    self.fields['eleve'].queryset = Eleve.objects.none()
            elif self.user.est_proved():
                if self.user.province_affectation:
                    ecoles = Ecole.objects.filter(province=self.user.province_affectation)
                    self.fields['ecole'].queryset = ecoles
                    self.fields['ecole'].initial = None
                    self.fields['niveau'].queryset = Niveau.objects.filter(ecole__in=ecoles, est_reference=False)
                    self.fields['classe'].queryset = Classe.objects.filter(ecole__in=ecoles, est_reference=False)
                    self.fields['cours'].queryset = Cours.objects.filter(ecole__in=ecoles, est_reference=False)
                    self.fields['eleve'].queryset = Eleve.objects.filter(ecole__in=ecoles)
                else:
                    self.fields['ecole'].queryset = Ecole.objects.none()
                    self.fields['niveau'].queryset = Niveau.objects.none()
                    self.fields['classe'].queryset = Classe.objects.none()
                    self.fields['cours'].queryset = Cours.objects.none()
                    self.fields['eleve'].queryset = Eleve.objects.none()
            else:
                # Admin
                self.fields['ecole'].queryset = Ecole.objects.all()
                self.fields['niveau'].queryset = Niveau.objects.filter(est_reference=False)
                self.fields['classe'].queryset = Classe.objects.filter(est_reference=False)
                self.fields['cours'].queryset = Cours.objects.filter(est_reference=False)
                self.fields['eleve'].queryset = Eleve.objects.all()
                self.fields['annee_scolaire'].queryset = AnneeScolaire.objects.all()


class EvaluationResultatForm(forms.Form):
    def __init__(self, eleve, cours, annee_scolaire, user=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.eleve = eleve
        self.cours = cours
        self.annee_scolaire = annee_scolaire
        self.user = user

        cycle_eval = CycleEvaluation.objects.filter(cours=cours).first()
        if cycle_eval:
            configs = cycle_eval.evaluations.all().order_by('cycle_num', 'ordre')
            for config in configs:
                field_name = f"eval_{config.id}"
                try:
                    resultat = EvaluationResultat.objects.get(
                        eleve=eleve,
                        cours=cours,
                        annee_scolaire=annee_scolaire,
                        evaluation_config=config
                    )
                    initial = resultat.points_obtenus
                except EvaluationResultat.DoesNotExist:
                    initial = None

                self.fields[field_name] = forms.DecimalField(
                    max_digits=5,
                    decimal_places=2,
                    min_value=0,
                    max_value=config.points_max,
                    required=False,
                    label=f"Cycle {config.cycle_num} - {config.get_type_display()}",
                    initial=initial,
                    widget=forms.NumberInput(attrs={
                        'class': 'form-control',
                        'step': '0.01',
                        'placeholder': f"0 - {config.points_max}"
                    })
                )
                self.fields[field_name].config_id = config.id

    def save(self):
        saved_count = 0
        for field_name, field in self.fields.items():
            if field_name.startswith('eval_'):
                config_id = field.config_id
                value = self.cleaned_data.get(field_name)
                if value is not None and value != '':
                    obj, created = EvaluationResultat.objects.update_or_create(
                        eleve=self.eleve,
                        cours=self.cours,
                        annee_scolaire=self.annee_scolaire,
                        evaluation_config_id=config_id,
                        defaults={'points_obtenus': value}
                    )
                    saved_count += 1
                else:
                    EvaluationResultat.objects.filter(
                        eleve=self.eleve,
                        cours=self.cours,
                        annee_scolaire=self.annee_scolaire,
                        evaluation_config_id=config_id
                    ).delete()
        return saved_count


# Nouveau formulaire pour la duplication de classe
class ClasseDuplicateForm(forms.Form):
    nouveau_nom = forms.CharField(
        max_length=50,
        label="Nom de la nouvelle classe",
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )

    def __init__(self, *args, **kwargs):
        self.source_classe = kwargs.pop('source_classe', None)
        self.ecole = kwargs.pop('ecole', None)
        self.niveau = kwargs.pop('niveau', None)
        super().__init__(*args, **kwargs)

    def clean_nouveau_nom(self):
        nom = self.cleaned_data['nouveau_nom']
        if self.ecole and self.niveau:
            if Classe.objects.filter(
                nom=nom,
                niveau=self.niveau,
                ecole=self.ecole,
                est_reference=False
            ).exists():
                raise forms.ValidationError("Une classe avec ce nom existe déjà pour ce niveau et cette école.")
        return nom