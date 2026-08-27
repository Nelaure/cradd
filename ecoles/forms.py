from django import forms
from django.forms import inlineformset_factory
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Row, Column, Field, Fieldset, Div, HTML, Submit
from .models import (
    Ecole, Niveau, Classe, Domaine, Cours, AnneeScolaire,
    CycleEvaluation, EvaluationConfig, EvaluationResultat, Province,
    Section, Option
)
from eleves.models import Eleve
from accounts.models import Utilisateur

# ===================== FORMULAIRES AVEC FILTRAGE PAR RÔLE =====================

class ProvinceForm(forms.ModelForm):
    class Meta:
        model = Province
        fields = ['nom', 'code', 'description']
        widgets = {
            'nom': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nom de la province'}),
            'code': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Code (ex: KN)'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Description'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.layout = Layout(
            Row(
                Column('nom', css_class='form-group col-md-6'),
                Column('code', css_class='form-group col-md-6'),
                css_class='row'
            ),
            Row(
                Column('description', css_class='form-group col-12'),
                css_class='row'
            ),
            Div(
                Submit('submit', 'Enregistrer', css_class='btn btn-primary'),
                HTML('<a href="{% url "ecoles:province_list" %}" class="btn btn-secondary">Annuler</a>'),
                css_class='text-end'
            )
        )


class EcoleForm(forms.ModelForm):
    niveaux_reference = forms.ModelMultipleChoiceField(
        queryset=Niveau.objects.filter(est_reference=True, ecole__isnull=True),
        required=False,
        label="Niveaux de référence à affecter",
        widget=forms.SelectMultiple(attrs={'class': 'form-select select2', 'data-placeholder': 'Sélectionnez les niveaux...'})
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
            'nom': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nom de l\'école'}),
            'code': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Code unique'}),
            'responsable': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nom du responsable'}),
            'contact': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Contact principal'}),
            'adresse': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Adresse complète'}),
            'telephone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Téléphone'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'email@exemple.com'}),
            'est_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        # Personnalisation de l'affichage des choix de niveaux de référence
        def label_from_instance(obj):
            nom = obj.nom
            section = obj.section.nom if obj.section else "Sans section"
            option = obj.option.nom if obj.option else "Sans option"
            return f"{nom} ({section} - {option})"
        self.fields['niveaux_reference'].label_from_instance = label_from_instance

        # Gestion de la province désactivée selon le rôle
        if self.user:
            if self.user.est_agent() or self.user.est_inspecteur() or self.user.est_proved():
                self.fields['province'].disabled = True
                if self.user.est_proved() and self.user.province_affectation:
                    self.fields['province'].initial = self.user.province_affectation.id
                    self.fields['province'].queryset = Province.objects.filter(id=self.user.province_affectation.id)
                elif self.user.est_agent() and self.user.ecole_affectation:
                    self.fields['province'].initial = self.user.ecole_affectation.province.id
                    self.fields['province'].queryset = Province.objects.filter(id=self.user.ecole_affectation.province.id)

        # Configuration de crispy forms
        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.layout = Layout(
            Fieldset(
                'Informations générales',
                Row(
                    Column('nom', css_class='form-group col-md-6'),
                    Column('code', css_class='form-group col-md-6'),
                    css_class='row'
                ),
                Row(
                    Column('province', css_class='form-group col-md-6'),
                    Column('type_gestion', css_class='form-group col-md-6'),
                    css_class='row'
                ),
            ),
            Fieldset(
                'Coordonnées',
                Row(
                    Column('responsable', css_class='form-group col-md-6'),
                    Column('contact', css_class='form-group col-md-6'),
                    css_class='row'
                ),
                Row(
                    Column('telephone', css_class='form-group col-md-6'),
                    Column('email', css_class='form-group col-md-6'),
                    css_class='row'
                ),
                Row(
                    Column('adresse', css_class='form-group col-12'),
                    css_class='row'
                ),
            ),
            Fieldset(
                'Statut et niveaux',
                Row(
                    Column('est_active', css_class='form-group col-12'),
                    css_class='row'
                ),
                Row(
                    Column('niveaux_reference', css_class='form-group col-12'),
                    css_class='row'
                ),
                HTML("""
                    <div class="form-text text-muted">
                        <i class="fas fa-info-circle"></i> Maintenez Ctrl (ou Cmd) pour sélectionner plusieurs niveaux.
                        Chaque niveau sera copié avec sa section et son option définies dans la référence.
                    </div>
                """),
            ),
            Div(
                Submit('submit', 'Enregistrer', css_class='btn btn-primary'),
                HTML('<a href="{% url "ecoles:ecole_list" %}" class="btn btn-secondary">Annuler</a>'),
                css_class='d-flex gap-2 justify-content-end mt-4'
            )
        )

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.user and self.user.est_proved() and self.user.province_affectation:
            instance.province = self.user.province_affectation
        if commit:
            instance.save()
            self.save_m2m()
        return instance


class NiveauForm(forms.ModelForm):
    section = forms.ModelChoiceField(
        queryset=Section.objects.all(),
        required=False,
        label="Section",
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    option = forms.ModelChoiceField(
        queryset=Option.objects.none(),
        required=False,
        label="Option",
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    class Meta:
        model = Niveau
        fields = ['nom', 'description', 'ordre', 'ecole', 'est_reference', 'section', 'option']
        widgets = {
            'nom': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Primaire, Secondaire...'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Description'}),
            'ordre': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '0'}),
            'ecole': forms.Select(attrs={'class': 'form-select'}),
            'est_reference': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        self.is_reference = kwargs.pop('is_reference', False)
        super().__init__(*args, **kwargs)

        section_id = None
        if self.data and 'section' in self.data:
            try:
                section_id = int(self.data.get('section'))
            except (TypeError, ValueError):
                pass
        if section_id is None and self.instance and self.instance.pk and self.instance.section:
            section_id = self.instance.section_id

        if section_id:
            self.fields['option'].queryset = Option.objects.filter(section_id=section_id)
        else:
            self.fields['option'].queryset = Option.objects.none()

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

        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.layout = Layout(
            Row(
                Column('nom', css_class='form-group col-md-6'),
                Column('ordre', css_class='form-group col-md-6'),
                css_class='row'
            ),
            Row(
                Column('ecole', css_class='form-group col-12'),
                css_class='row'
            ),
            Row(
                Column('est_reference', css_class='form-group col-12'),
                css_class='row'
            ),
            Row(
                Column('section', css_class='form-group col-md-6'),
                Column('option', css_class='form-group col-md-6'),
                css_class='row'
            ),
            Row(
                Column('description', css_class='form-group col-12'),
                css_class='row'
            ),
            Div(
                Submit('submit', 'Enregistrer', css_class='btn btn-primary'),
                HTML('<a href="{% url "ecoles:niveau_list" %}" class="btn btn-secondary">Annuler</a>'),
                css_class='d-flex gap-2 justify-content-end mt-4'
            )
        )

    def clean(self):
        cleaned_data = super().clean()
        section = cleaned_data.get('section')
        option = cleaned_data.get('option')
        if option and section and option.section != section:
            raise forms.ValidationError("L'option choisie ne correspond pas à la section sélectionnée.")
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
            'nom': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: 6ème A'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Description'}),
            'ordre': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '0'}),
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

        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.layout = Layout(
            Row(
                Column('nom', css_class='form-group col-md-6'),
                Column('ordre', css_class='form-group col-md-6'),
                css_class='row'
            ),
            Row(
                Column('niveau', css_class='form-group col-md-6'),
                Column('ecole', css_class='form-group col-md-6'),
                css_class='row'
            ),
            Row(
                Column('est_reference', css_class='form-group col-12'),
                css_class='row'
            ),
            Row(
                Column('description', css_class='form-group col-12'),
                css_class='row'
            ),
            Div(
                Submit('submit', 'Enregistrer', css_class='btn btn-primary'),
                HTML('<a href="{% url "ecoles:classe_list" %}" class="btn btn-secondary">Annuler</a>'),
                css_class='d-flex gap-2 justify-content-end mt-4'
            )
        )

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
            'nom': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nom du domaine'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Description'}),
            'ecole': forms.Select(attrs={'class': 'form-select'}),
            'est_reference': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'niveaux': forms.SelectMultiple(attrs={'class': 'form-select select2'}),
            'classes': forms.SelectMultiple(attrs={'class': 'form-select select2'}),
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

        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.layout = Layout(
            Row(
                Column('nom', css_class='form-group col-md-6'),
                Column('ecole', css_class='form-group col-md-6'),
                css_class='row'
            ),
            Row(
                Column('est_reference', css_class='form-group col-12'),
                css_class='row'
            ),
            Row(
                Column('niveaux', css_class='form-group col-12'),
                css_class='row'
            ),
            Row(
                Column('classes', css_class='form-group col-12'),
                css_class='row'
            ),
            Row(
                Column('description', css_class='form-group col-12'),
                css_class='row'
            ),
            Div(
                Submit('submit', 'Enregistrer', css_class='btn btn-primary'),
                HTML('<a href="{% url "ecoles:domaine_list" %}" class="btn btn-secondary">Annuler</a>'),
                css_class='d-flex gap-2 justify-content-end mt-4'
            )
        )

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
            'nom': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nom du cours'}),
            'code': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Code unique'}),
            'coefficient': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '1'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Description'}),
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

        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.layout = Layout(
            Row(
                Column('nom', css_class='form-group col-md-6'),
                Column('code', css_class='form-group col-md-6'),
                css_class='row'
            ),
            Row(
                Column('coefficient', css_class='form-group col-md-4'),
                Column('niveau', css_class='form-group col-md-4'),
                Column('classe', css_class='form-group col-md-4'),
                css_class='row'
            ),
            Row(
                Column('domaine', css_class='form-group col-md-6'),
                Column('ecole', css_class='form-group col-md-6'),
                css_class='row'
            ),
            Row(
                Column('est_reference', css_class='form-group col-12'),
                css_class='row'
            ),
            Row(
                Column('description', css_class='form-group col-12'),
                css_class='row'
            ),
            Div(
                Submit('submit', 'Enregistrer', css_class='btn btn-primary'),
                HTML('<a href="{% url "ecoles:cours_list" %}" class="btn btn-secondary">Annuler</a>'),
                css_class='d-flex gap-2 justify-content-end mt-4'
            )
        )

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
            'annee': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: 2024-2025'}),
            'date_debut': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'date_fin': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'est_actuelle': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'ecoles': forms.SelectMultiple(attrs={'class': 'form-select select2'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['ecoles'].queryset = Ecole.objects.all()
        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.layout = Layout(
            Row(
                Column('annee', css_class='form-group col-md-6'),
                Column('est_actuelle', css_class='form-group col-md-6'),
                css_class='row'
            ),
            Row(
                Column('date_debut', css_class='form-group col-md-6'),
                Column('date_fin', css_class='form-group col-md-6'),
                css_class='row'
            ),
            Row(
                Column('ecoles', css_class='form-group col-12'),
                css_class='row'
            ),
            Div(
                Submit('submit', 'Enregistrer', css_class='btn btn-primary'),
                HTML('<a href="{% url "ecoles:annee_list" %}" class="btn btn-secondary">Annuler</a>'),
                css_class='d-flex gap-2 justify-content-end mt-4'
            )
        )


class CycleEvaluationForm(forms.ModelForm):
    class Meta:
        model = CycleEvaluation
        fields = ['type_cycle']
        widgets = {
            'type_cycle': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.layout = Layout(
            Row(
                Column('type_cycle', css_class='form-group col-12'),
                css_class='row'
            ),
            Div(
                Submit('submit', 'Enregistrer', css_class='btn btn-primary'),
                HTML('<a href="{% url "ecoles:cours_list" %}" class="btn btn-secondary">Annuler</a>'),
                css_class='d-flex gap-2 justify-content-end mt-4'
            )
        )


class EvaluationConfigForm(forms.ModelForm):
    class Meta:
        model = EvaluationConfig
        fields = ['cycle_num', 'periode_num', 'type', 'points_max', 'ordre']
        widgets = {
            'cycle_num': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '1'}),
            'periode_num': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '1'}),
            'type': forms.Select(attrs={'class': 'form-select'}),
            'points_max': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '20'}),
            'ordre': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '0'}),
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
                self.fields['ecole'].queryset = Ecole.objects.all()
                self.fields['niveau'].queryset = Niveau.objects.filter(est_reference=False)
                self.fields['classe'].queryset = Classe.objects.filter(est_reference=False)
                self.fields['cours'].queryset = Cours.objects.filter(est_reference=False)
                self.fields['eleve'].queryset = Eleve.objects.all()
                self.fields['annee_scolaire'].queryset = AnneeScolaire.objects.all()

        self.helper = FormHelper()
        self.helper.form_method = 'get'
        self.helper.layout = Layout(
            Row(
                Column('ecole', css_class='form-group col-md-4'),
                Column('niveau', css_class='form-group col-md-4'),
                Column('classe', css_class='form-group col-md-4'),
                css_class='row'
            ),
            Row(
                Column('eleve', css_class='form-group col-md-6'),
                Column('cours', css_class='form-group col-md-6'),
                css_class='row'
            ),
            Row(
                Column('annee_scolaire', css_class='form-group col-12'),
                css_class='row'
            ),
            Div(
                Submit('submit', 'Rechercher', css_class='btn btn-primary'),
                css_class='d-flex justify-content-end mt-3'
            )
        )


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

        self.helper = FormHelper()
        self.helper.form_method = 'post'
        layout_fields = []
        for field_name in self.fields:
            layout_fields.append(Field(field_name, css_class='form-group col-md-4'))
        layout_fields.append(
            Div(
                Submit('submit', 'Enregistrer', css_class='btn btn-primary'),
                HTML('<a href="{% url "ecoles:resultat_list" %}" class="btn btn-secondary">Annuler</a>'),
                css_class='d-flex gap-2 justify-content-end mt-4'
            )
        )
        self.helper.layout = Layout(
            Row(*layout_fields, css_class='row'),
        )

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


class ClasseDuplicateForm(forms.Form):
    nouveau_nom = forms.CharField(
        max_length=50,
        label="Nom de la nouvelle classe",
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: 6ème A (copie)'})
    )

    def __init__(self, *args, **kwargs):
        self.source_classe = kwargs.pop('source_classe', None)
        self.ecole = kwargs.pop('ecole', None)
        self.niveau = kwargs.pop('niveau', None)
        super().__init__(*args, **kwargs)

        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.layout = Layout(
            Row(
                Column('nouveau_nom', css_class='form-group col-12'),
                css_class='row'
            ),
            Div(
                Submit('submit', 'Dupliquer', css_class='btn btn-success'),
                HTML('<a href="{% url "ecoles:classe_list" %}" class="btn btn-secondary">Annuler</a>'),
                css_class='d-flex gap-2 justify-content-end mt-4'
            )
        )

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


class SectionForm(forms.ModelForm):
    class Meta:
        model = Section
        fields = ['nom', 'code', 'description', 'ordre']
        widgets = {
            'nom': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Enseignement Général'}),
            'code': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Code unique'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Description'}),
            'ordre': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '0'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.layout = Layout(
            Row(
                Column('nom', css_class='form-group col-md-6'),
                Column('code', css_class='form-group col-md-6'),
                css_class='row'
            ),
            Row(
                Column('ordre', css_class='form-group col-md-6'),
                css_class='row'
            ),
            Row(
                Column('description', css_class='form-group col-12'),
                css_class='row'
            ),
            Div(
                Submit('submit', 'Enregistrer', css_class='btn btn-primary'),
                HTML('<a href="{% url "ecoles:section_list" %}" class="btn btn-secondary">Annuler</a>'),
                css_class='d-flex gap-2 justify-content-end mt-4'
            )
        )


class OptionForm(forms.ModelForm):
    class Meta:
        model = Option
        fields = ['nom', 'code', 'section', 'description', 'ordre']
        widgets = {
            'nom': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Latin-Philosophie'}),
            'code': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Code unique'}),
            'section': forms.Select(attrs={'class': 'form-select'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Description'}),
            'ordre': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '0'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.layout = Layout(
            Row(
                Column('nom', css_class='form-group col-md-6'),
                Column('code', css_class='form-group col-md-6'),
                css_class='row'
            ),
            Row(
                Column('section', css_class='form-group col-md-6'),
                Column('ordre', css_class='form-group col-md-6'),
                css_class='row'
            ),
            Row(
                Column('description', css_class='form-group col-12'),
                css_class='row'
            ),
            Div(
                Submit('submit', 'Enregistrer', css_class='btn btn-primary'),
                HTML('<a href="{% url "ecoles:option_list" %}" class="btn btn-secondary">Annuler</a>'),
                css_class='d-flex gap-2 justify-content-end mt-4'
            )
        )