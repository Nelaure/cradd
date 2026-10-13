from django import forms
from django.forms import inlineformset_factory
from django.db.models import Min, Q
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Row, Column, Field, Fieldset, Div, HTML, Submit
from .models import (
    Ecole, Niveau, Classe, Cours, AnneeScolaire,
    CycleEvaluation, EvaluationConfig, EvaluationResultat, Province,
    Section
)
from eleves.models import Eleve
from accounts.models import Utilisateur


# ===================== PROVINCE =====================

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


# ===================== ECOLE =====================

class EcoleForm(forms.ModelForm):
    niveaux_reference = forms.ModelMultipleChoiceField(
        queryset=Niveau.objects.filter(est_reference=True, ecole__isnull=True),
        required=False,
        label="Niveaux de référence à affecter",
        widget=forms.SelectMultiple(attrs={
            'class': 'form-select select2',
            'data-placeholder': 'Sélectionnez les niveaux...'
        })
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
        fields = ['nom', 'code', 'province', 'type_gestion', 'responsable',
                  'contact', 'adresse', 'telephone', 'email', 'est_active']
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

        def label_from_instance(obj):
            nom = obj.nom
            section = obj.section.nom if obj.section else "Sans section"
            return f"{nom} ({section})"
        self.fields['niveaux_reference'].label_from_instance = label_from_instance

        if self.user:
            if self.user.est_ministre():
                for field in self.fields.values():
                    field.disabled = True
            elif self.user.est_agent() or self.user.est_inspecteur() or self.user.est_proved():
                self.fields['province'].disabled = True
                if self.user.est_proved() and self.user.province_affectation:
                    self.fields['province'].initial = self.user.province_affectation.id
                    self.fields['province'].queryset = Province.objects.filter(
                        id=self.user.province_affectation.id
                    )
                elif self.user.est_agent() and self.user.ecole_affectation:
                    self.fields['province'].initial = self.user.ecole_affectation.province.id
                    self.fields['province'].queryset = Province.objects.filter(
                        id=self.user.ecole_affectation.province.id
                    )

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
                        Chaque niveau sera copié avec sa section définie dans la référence.
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


# ===================== NIVEAU =====================

class NiveauForm(forms.ModelForm):
    section = forms.ModelChoiceField(
        queryset=Section.objects.all(),
        required=False,
        label="Section",
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    class Meta:
        model = Niveau
        fields = ['nom', 'description', 'ordre', 'ecole', 'est_reference', 'section']
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

        if self.is_reference:
            self.fields['ecole'].queryset = Ecole.objects.none()
            self.fields['ecole'].widget = forms.HiddenInput()
            self.fields['ecole'].required = False
            self.fields['est_reference'].initial = True
            self.fields['est_reference'].disabled = True
        else:
            if self.user:
                if self.user.est_ministre():
                    for field in self.fields.values():
                        field.disabled = True
                elif self.user.est_enseignant():
                    for field in self.fields:
                        self.fields[field].disabled = True
                elif self.user.est_agent() or self.user.est_inspecteur():
                    if self.user.ecole_affectation:
                        self.fields['ecole'].queryset = Ecole.objects.filter(
                            id=self.user.ecole_affectation.id
                        )
                        self.fields['ecole'].initial = self.user.ecole_affectation.id
                        self.fields['ecole'].disabled = True
                    else:
                        self.fields['ecole'].queryset = Ecole.objects.none()
                elif self.user.est_proved():
                    self.fields['ecole'].queryset = Ecole.objects.filter(
                        province=self.user.province_affectation
                    ) if self.user.province_affectation else Ecole.objects.none()
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
                Column('section', css_class='form-group col-12'),
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

        if self.is_reference:
            nom = cleaned_data.get('nom')
            section = cleaned_data.get('section')
            if nom and section:
                existing = Niveau.objects.filter(
                    est_reference=True,
                    ecole__isnull=True,
                    nom=nom,
                    section=section
                ).exclude(pk=self.instance.pk).exists()
                if existing:
                    raise forms.ValidationError(
                        f"Un niveau de référence avec le nom '{nom}' et la section "
                        f"'{section.nom}' existe déjà."
                    )
        return cleaned_data


# ===================== CLASSE =====================

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
            self.fields['niveau'].queryset = Niveau.objects.filter(
                est_reference=True, ecole__isnull=True
            )
        else:
            if self.user:
                if self.user.est_ministre():
                    for field in self.fields.values():
                        field.disabled = True
                elif self.user.est_enseignant():
                    for field in self.fields:
                        self.fields[field].disabled = True
                elif self.user.est_agent() or self.user.est_inspecteur():
                    if self.user.ecole_affectation:
                        self.fields['ecole'].queryset = Ecole.objects.filter(
                            id=self.user.ecole_affectation.id
                        )
                        self.fields['ecole'].initial = self.user.ecole_affectation.id
                        self.fields['ecole'].disabled = True
                        self.fields['niveau'].queryset = Niveau.objects.filter(
                            ecole=self.user.ecole_affectation,
                            est_reference=False
                        )
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
                        self.fields['niveau'].queryset = Niveau.objects.filter(
                            ecole__in=ecoles, est_reference=False
                        )
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


# ===================== COURS (SANS DOMAINE) =====================

class CoursForm(forms.ModelForm):
    """
    Formulaire de création/modification d'un cours (SANS domaine).

    RÈGLE IMPORTANTE :
    - En mode CRÉATION : le champ `classe` est vide au départ, puis rempli
      dynamiquement via l'API `/api/classes-par-niveau/` quand l'utilisateur
      change le niveau.
    - En mode MODIFICATION : le champ `classe` n'affiche QUE les classes
      appartenant au niveau actuel du cours (filtrage strict par niveau).
    """

    classe = forms.ModelMultipleChoiceField(
        queryset=Classe.objects.none(),
        required=True,
        label="Classes",
        widget=forms.SelectMultiple(attrs={
            'class': 'form-select',
            'size': '8',
        })
    )

    class Meta:
        model = Cours
        fields = ['nom', 'code', 'coefficient', 'description', 'niveau',
                  'ecole', 'est_reference']
        widgets = {
            'nom': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nom du cours'}),
            'code': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Code unique'}),
            'coefficient': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '1'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Description'}),
            'niveau': forms.Select(attrs={'class': 'form-select'}),
            'ecole': forms.Select(attrs={'class': 'form-select'}),
            'est_reference': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        self.is_reference = kwargs.pop('is_reference', False)
        super().__init__(*args, **kwargs)

        # ============================================================
        # 1. CONFIGURATION DES QUERYSETS DE BASE
        # ============================================================
        if self.is_reference:
            # ----- Mode référence -----
            self.fields['ecole'].queryset = Ecole.objects.none()
            self.fields['ecole'].widget = forms.HiddenInput()
            self.fields['ecole'].required = False
            self.fields['est_reference'].initial = True
            self.fields['est_reference'].disabled = True

            self.fields['niveau'].queryset = Niveau.objects.filter(
                est_reference=True, ecole__isnull=True,
            ).order_by('nom')

            # ⚠️ Le queryset de `classe` sera défini plus bas selon le contexte

        else:
            # ----- Mode instance -----
            if self.user:
                if self.user.est_ministre():
                    for field in self.fields.values():
                        field.disabled = True
                elif self.user.est_enseignant():
                    for field in self.fields:
                        self.fields[field].disabled = True
                    if self.user.classe_affectation:
                        self.fields['classe'].queryset = Classe.objects.filter(
                            id=self.user.classe_affectation.id
                        )
                        self.fields['niveau'].queryset = Niveau.objects.filter(
                            id=self.user.niveau_affectation.id
                        ) if self.user.niveau_affectation else Niveau.objects.none()
                        self.fields['ecole'].queryset = Ecole.objects.filter(
                            id=self.user.ecole_affectation.id
                        )
                        self.fields['ecole'].disabled = True
                elif self.user.est_agent() or self.user.est_inspecteur():
                    if self.user.ecole_affectation:
                        self.fields['ecole'].queryset = Ecole.objects.filter(
                            id=self.user.ecole_affectation.id
                        )
                        self.fields['ecole'].initial = self.user.ecole_affectation.id
                        self.fields['ecole'].disabled = True
                        self.fields['niveau'].queryset = Niveau.objects.filter(
                            ecole=self.user.ecole_affectation, est_reference=False
                        )
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
                        self.fields['niveau'].queryset = Niveau.objects.filter(
                            ecole__in=ecoles, est_reference=False
                        )
                    else:
                        self.fields['ecole'].queryset = Ecole.objects.none()
                        self.fields['niveau'].queryset = Niveau.objects.none()
                else:
                    self.fields['ecole'].queryset = Ecole.objects.all()
                    self.fields['niveau'].queryset = Niveau.objects.filter(est_reference=False)

        # ============================================================
        # 2. GESTION DU QUERYSET DE `classe`
        # ============================================================
        if self.instance.pk and self.instance.niveau_id:
            # ----- MODE MODIFICATION : filtrer par niveau du cours -----
            # On n'affiche QUE les classes qui appartiennent au niveau du cours.
            niveau_courant = self.instance.niveau

            if self.is_reference:
                # Classes de référence du même niveau
                classes_du_niveau = Classe.objects.filter(
                    niveau=niveau_courant,
                    est_reference=True,
                    ecole__isnull=True,
                ).order_by('nom')
            else:
                # Classes d'instance du même niveau (même école)
                classes_du_niveau = Classe.objects.filter(
                    niveau=niveau_courant,
                    ecole=self.instance.ecole,
                    est_reference=False,
                ).order_by('nom')

            # Filtrer selon l'école et le rôle de l'utilisateur (sécurité)
            if self.user:
                if self.user.est_agent() or self.user.est_inspecteur():
                    if self.user.ecole_affectation:
                        classes_du_niveau = classes_du_niveau.filter(
                            ecole=self.user.ecole_affectation
                        )
                elif self.user.est_proved() and self.user.province_affectation:
                    classes_du_niveau = classes_du_niveau.filter(
                        ecole__province=self.user.province_affectation
                    )

            self.fields['classe'].queryset = classes_du_niveau

            # Pré-sélectionner la classe actuelle
            if self.instance.classe_id:
                self.fields['classe'].initial = [self.instance.classe_id]

        else:
            # ----- MODE CRÉATION : queryset vide -----
            # Le JS remplira dynamiquement via l'API
            self.fields['classe'].queryset = Classe.objects.none()

        # ============================================================
        # 3. LAYOUT CRISPY
        # ============================================================
        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.layout = Layout(
            Row(
                Column('nom', css_class='form-group col-md-6'),
                Column('code', css_class='form-group col-md-6'),
                css_class='row'
            ),
            Row(
                Column('coefficient', css_class='form-group col-md-6'),
                Column('niveau', css_class='form-group col-md-6'),
                css_class='row'
            ),
            Row(
                Column('classe', css_class='form-group col-12'),
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
                    cleaned_data['classe'] = Classe.objects.filter(
                        id=self.user.classe_affectation.id
                    )
                    cleaned_data['niveau'] = self.user.niveau_affectation
                    cleaned_data['ecole'] = self.user.ecole_affectation
                else:
                    raise forms.ValidationError("Vous devez être affecté à une classe.")
            elif self.user and self.user.est_proved():
                ecole = cleaned_data.get('ecole')
                if ecole and ecole.province != self.user.province_affectation:
                    raise forms.ValidationError("L'école choisie n'appartient pas à votre province.")
        return cleaned_data


# ===================== CYCLE CONFIG (CRÉATION) =====================

class CycleEvaluationConfigForm(forms.Form):
    CYCLE_TYPES = (
        ('trimestre', 'Trimestriel (3 cycles)'),
        ('semestre', 'Semestriel (2 cycles)'),
    )

    config_active = forms.CharField(
        required=False,
        widget=forms.HiddenInput(attrs={'id': 'id_config_active'})
    )
    type_cycle = forms.ChoiceField(
        choices=CYCLE_TYPES,
        initial='trimestre',
        required=False,
        label="Type de cycle",
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'id_type_cycle'})
    )
    nombre_cycles = forms.IntegerField(
        min_value=1, max_value=6, initial=3, required=False,
        label="Nombre de cycles",
        widget=forms.NumberInput(attrs={
            'class': 'form-control', 'id': 'id_nombre_cycles', 'placeholder': '3'
        })
    )
    periodes_par_cycle = forms.IntegerField(
        min_value=1, max_value=5, initial=2, required=False,
        label="Périodes par cycle",
        widget=forms.NumberInput(attrs={
            'class': 'form-control', 'id': 'id_periodes_par_cycle', 'placeholder': '2'
        })
    )
    inclure_examen = forms.BooleanField(
        initial=True, required=False,
        label="Inclure un examen par cycle (valeur ×2)",
        widget=forms.CheckboxInput(attrs={
            'class': 'form-check-input', 'id': 'id_inclure_examen'
        })
    )
    points_max = forms.IntegerField(
        min_value=1, max_value=100, initial=20, required=False,
        label="Points max par période",
        help_text="L'examen vaudra automatiquement le double.",
        widget=forms.NumberInput(attrs={
            'class': 'form-control', 'id': 'id_points_max', 'placeholder': '20'
        })
    )

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        self.is_reference = kwargs.pop('is_reference', False)
        super().__init__(*args, **kwargs)
        if self.user and self.user.est_ministre():
            for field in self.fields.values():
                field.disabled = True
        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.layout = Layout()

    def is_active(self):
        return bool(self.cleaned_data.get('config_active')) if self.is_valid() else False

    def get_config(self):
        if not self.is_valid() or not self.is_active():
            return None
        cd = self.cleaned_data
        return {
            'type_cycle': cd.get('type_cycle') or 'trimestre',
            'nombre_cycles': cd.get('nombre_cycles') or 3,
            'periodes_par_cycle': cd.get('periodes_par_cycle') or 2,
            'inclure_examen': cd.get('inclure_examen', True),
            'points_max': cd.get('points_max') or 20,
        }


# ===================== ANNÉE SCOLAIRE =====================

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


# ===================== CYCLE D'ÉVALUATION (ÉDITION) =====================

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


class EvaluationConfigFormSet(forms.BaseInlineFormSet):
    def clean(self):
        super().clean()
        seen = set()
        for form in self.forms:
            if form.cleaned_data and not form.cleaned_data.get('DELETE', False):
                cycle_num = form.cleaned_data.get('cycle_num')
                periode_num = form.cleaned_data.get('periode_num')
                eval_type = form.cleaned_data.get('type')
                if cycle_num and eval_type:
                    key = (cycle_num, periode_num, eval_type)
                    if key in seen:
                        raise forms.ValidationError(
                            f"Doublon : Cycle {cycle_num}, {eval_type} "
                            f"{f'Période {periode_num}' if eval_type == 'periode' else ''} "
                            f"apparaît plusieurs fois."
                        )
                    seen.add(key)


EvaluationConfigFormSet = inlineformset_factory(
    CycleEvaluation,
    EvaluationConfig,
    form=EvaluationConfigForm,
    formset=EvaluationConfigFormSet,
    extra=1,
    can_delete=True,
    min_num=0,
)


# ===================== RÉSULTATS =====================

class ResultatSelectionForm(forms.Form):
    ecole = forms.ModelChoiceField(
        queryset=Ecole.objects.all(), required=False, label="École",
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    niveau = forms.ModelChoiceField(
        queryset=Niveau.objects.filter(est_reference=False),
        required=False, label="Niveau",
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    classe = forms.ModelChoiceField(
        queryset=Classe.objects.filter(est_reference=False),
        required=False, label="Classe",
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    eleve = forms.ModelChoiceField(
        queryset=Eleve.objects.all(), required=False, label="Élève",
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    cours = forms.ModelChoiceField(
        queryset=Cours.objects.none(), required=False, label="Cours",
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    annee_scolaire = forms.ModelChoiceField(
        queryset=AnneeScolaire.objects.all(), required=False, label="Année scolaire",
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        def cours_label(obj):
            ecole_nom = obj.ecole.nom if obj.ecole else "Réf."
            return f"{obj.nom} ({obj.classe.nom} - {ecole_nom})"

        self.fields['cours'].label_from_instance = cours_label

        base_qs = Cours.objects.filter(est_reference=False)

        distinct_ids = (
            base_qs
            .values('nom', 'classe', 'ecole')
            .annotate(min_id=Min('id'))
            .values_list('min_id', flat=True)
        )
        distinct_cours_qs = (
            Cours.objects
            .filter(id__in=distinct_ids)
            .select_related('classe', 'ecole', 'niveau')
            .order_by('nom')
        )

        if self.user:
            if self.user.est_ministre():
                self.fields['ecole'].queryset = Ecole.objects.none()
                self.fields['niveau'].queryset = Niveau.objects.none()
                self.fields['classe'].queryset = Classe.objects.none()
                self.fields['eleve'].queryset = Eleve.objects.none()
                self.fields['cours'].queryset = Cours.objects.none()

            elif self.user.est_enseignant():
                if self.user.ecole_affectation:
                    self.fields['ecole'].queryset = Ecole.objects.filter(
                        id=self.user.ecole_affectation.id
                    )
                    self.fields['ecole'].initial = self.user.ecole_affectation.id
                    self.fields['ecole'].disabled = True
                else:
                    self.fields['ecole'].queryset = Ecole.objects.none()

                if self.user.niveau_affectation:
                    self.fields['niveau'].queryset = Niveau.objects.filter(
                        id=self.user.niveau_affectation.id
                    )
                    self.fields['niveau'].initial = self.user.niveau_affectation.id
                    self.fields['niveau'].disabled = True
                else:
                    self.fields['niveau'].queryset = Niveau.objects.none()

                if self.user.classe_affectation:
                    self.fields['classe'].queryset = Classe.objects.filter(
                        id=self.user.classe_affectation.id
                    )
                    self.fields['classe'].initial = self.user.classe_affectation.id
                    self.fields['classe'].disabled = True

                    self.fields['eleve'].queryset = Eleve.objects.filter(
                        classe=self.user.classe_affectation
                    )

                    self.fields['cours'].queryset = distinct_cours_qs.filter(
                        classe=self.user.classe_affectation,
                        ecole=self.user.ecole_affectation,
                    )
                else:
                    self.fields['classe'].queryset = Classe.objects.none()
                    self.fields['eleve'].queryset = Eleve.objects.none()
                    self.fields['cours'].queryset = distinct_cours_qs.none()

            elif self.user.est_agent() or self.user.est_inspecteur():
                if self.user.ecole_affectation:
                    self.fields['ecole'].queryset = Ecole.objects.filter(
                        id=self.user.ecole_affectation.id
                    )
                    self.fields['ecole'].initial = self.user.ecole_affectation.id
                    self.fields['ecole'].disabled = True
                    self.fields['niveau'].queryset = Niveau.objects.filter(
                        ecole=self.user.ecole_affectation, est_reference=False
                    )
                    self.fields['classe'].queryset = Classe.objects.filter(
                        ecole=self.user.ecole_affectation, est_reference=False
                    )
                    self.fields['eleve'].queryset = Eleve.objects.filter(
                        ecole=self.user.ecole_affectation
                    )
                    self.fields['cours'].queryset = distinct_cours_qs.filter(
                        ecole=self.user.ecole_affectation
                    )
                else:
                    self.fields['ecole'].queryset = Ecole.objects.none()
                    self.fields['niveau'].queryset = Niveau.objects.none()
                    self.fields['classe'].queryset = Classe.objects.none()
                    self.fields['eleve'].queryset = Eleve.objects.none()
                    self.fields['cours'].queryset = distinct_cours_qs.none()

            elif self.user.est_proved():
                if self.user.province_affectation:
                    ecoles = Ecole.objects.filter(province=self.user.province_affectation)
                    self.fields['ecole'].queryset = ecoles
                    self.fields['niveau'].queryset = Niveau.objects.filter(
                        ecole__in=ecoles, est_reference=False
                    )
                    self.fields['classe'].queryset = Classe.objects.filter(
                        ecole__in=ecoles, est_reference=False
                    )
                    self.fields['eleve'].queryset = Eleve.objects.filter(
                        ecole__in=ecoles
                    )
                    self.fields['cours'].queryset = distinct_cours_qs.filter(
                        ecole__in=ecoles
                    )
                else:
                    self.fields['ecole'].queryset = Ecole.objects.none()
                    self.fields['niveau'].queryset = Niveau.objects.none()
                    self.fields['classe'].queryset = Classe.objects.none()
                    self.fields['cours'].queryset = distinct_cours_qs.none()
                    self.fields['eleve'].queryset = Eleve.objects.none()

            else:
                self.fields['ecole'].queryset = Ecole.objects.all()
                self.fields['niveau'].queryset = Niveau.objects.filter(est_reference=False)
                self.fields['classe'].queryset = Classe.objects.filter(est_reference=False)
                self.fields['cours'].queryset = distinct_cours_qs
                self.fields['eleve'].queryset = Eleve.objects.all()

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
    def __init__(self, eleve, cours, annee_scolaire, user=None, configs=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.eleve = eleve
        self.cours = cours
        self.annee_scolaire = annee_scolaire
        self.user = user

        if configs is None:
            cycle_eval = CycleEvaluation.objects.filter(cours=cours).first()
            if cycle_eval:
                configs = cycle_eval.evaluations.filter(
                    cycle_num__lte=cycle_eval.get_nombre_cycles()
                ).order_by('cycle_num', 'ordre')
            else:
                configs = []

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

            label = f"Cycle {config.cycle_num} - "
            label += f"Période {config.periode_num}" if config.type == 'periode' else "Examen"

            self.fields[field_name] = forms.DecimalField(
                max_digits=5, decimal_places=2,
                min_value=0, max_value=config.points_max,
                required=False, label=label, initial=initial,
                widget=forms.NumberInput(attrs={
                    'class': 'form-control', 'step': '0.01',
                    'placeholder': f"0 - {config.points_max}"
                })
            )
            self.fields[field_name].config_id = config.id
            self.fields[field_name].cycle_num = config.cycle_num
            self.fields[field_name].periode_num = config.periode_num
            self.fields[field_name].eval_type = config.type
            self.fields[field_name].points_max = config.points_max

        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.layout = Layout()

    def save(self):
        saved_count = 0
        for field_name, field in self.fields.items():
            if field_name.startswith('eval_'):
                config_id = field.config_id
                value = self.cleaned_data.get(field_name)
                if value is not None and value != '':
                    EvaluationResultat.objects.update_or_create(
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


# ===================== DUPLICATION CLASSE =====================

class ClasseDuplicateForm(forms.Form):
    nouveau_nom = forms.CharField(
        max_length=50,
        label="Nom de la nouvelle classe",
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Ex: 6ème A (copie)'
        })
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
                nom=nom, niveau=self.niveau, ecole=self.ecole, est_reference=False
            ).exists():
                raise forms.ValidationError(
                    "Une classe avec ce nom existe déjà pour ce niveau et cette école."
                )
        return nom


# ===================== SECTION =====================

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