from django import forms
from .models import Eleve, Bulletin
from ecoles.models import Ecole, Niveau, Classe, AnneeScolaire

class EleveForm(forms.ModelForm):
    class Meta:
        model = Eleve
        fields = ['nom', 'postnom', 'prenom', 'sexe', 'date_naissance', 'lieu_naissance',
                  'telephone', 'email', 'adresse', 'matricule', 'ecole', 'niveau',
                  'classe', 'annee_scolaire', 'photo']
        widgets = {
            'nom': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nom'}),
            'postnom': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Postnom (facultatif)'}),
            'prenom': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Prénom'}),
            'sexe': forms.Select(attrs={'class': 'form-select'}),
            'date_naissance': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'lieu_naissance': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Lieu de naissance'}),
            'telephone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Téléphone'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'email@exemple.com'}),
            'adresse': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Adresse'}),
            'matricule': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Matricule'}),
            'ecole': forms.Select(attrs={'class': 'form-select', 'id': 'id_ecole'}),
            'niveau': forms.Select(attrs={'class': 'form-select', 'id': 'id_niveau'}),
            'classe': forms.Select(attrs={'class': 'form-select', 'id': 'id_classe'}),
            'annee_scolaire': forms.Select(attrs={'class': 'form-select'}),
            'photo': forms.FileInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        # Restreindre les choix selon le rôle
        if user:
            if user.est_enseignant():
                # Enseignant : école et classe figées
                if user.ecole_affectation:
                    self.fields['ecole'].queryset = Ecole.objects.filter(id=user.ecole_affectation.id)
                    self.fields['ecole'].initial = user.ecole_affectation.id
                    self.fields['ecole'].disabled = True
                    self.fields['niveau'].queryset = Niveau.objects.filter(ecole=user.ecole_affectation, est_reference=False)
                    if user.niveau_affectation:
                        self.fields['niveau'].initial = user.niveau_affectation.id
                        self.fields['niveau'].disabled = True
                    self.fields['classe'].queryset = Classe.objects.filter(ecole=user.ecole_affectation, est_reference=False)
                    if user.classe_affectation:
                        self.fields['classe'].initial = user.classe_affectation.id
                        self.fields['classe'].disabled = True
                else:
                    # Pas d'école -> pas de choix
                    self.fields['ecole'].queryset = Ecole.objects.none()
                    self.fields['niveau'].queryset = Niveau.objects.none()
                    self.fields['classe'].queryset = Classe.objects.none()

            elif user.est_agent() or user.est_inspecteur():
                # Agent/Inspecteur : école figée, niveau/classe libres dans son école
                if user.ecole_affectation:
                    self.fields['ecole'].queryset = Ecole.objects.filter(id=user.ecole_affectation.id)
                    self.fields['ecole'].initial = user.ecole_affectation.id
                    self.fields['ecole'].disabled = True
                    self.fields['niveau'].queryset = Niveau.objects.filter(ecole=user.ecole_affectation, est_reference=False)
                    self.fields['classe'].queryset = Classe.objects.filter(ecole=user.ecole_affectation, est_reference=False)
                else:
                    self.fields['ecole'].queryset = Ecole.objects.none()
                    self.fields['niveau'].queryset = Niveau.objects.none()
                    self.fields['classe'].queryset = Classe.objects.none()
            else:
                # Administrateur : tout visible
                self.fields['ecole'].queryset = Ecole.objects.all()
                self.fields['niveau'].queryset = Niveau.objects.filter(est_reference=False)
                self.fields['classe'].queryset = Classe.objects.filter(est_reference=False)

        # Filtrage dynamique pour les cascades (si données POST)
        if self.data:
            ecole_id = self.data.get('ecole')
            if ecole_id:
                try:
                    ecole_id = int(ecole_id)
                    self.fields['niveau'].queryset = Niveau.objects.filter(ecole_id=ecole_id, est_reference=False)
                    niveau_id = self.data.get('niveau')
                    if niveau_id:
                        self.fields['classe'].queryset = Classe.objects.filter(niveau_id=niveau_id, est_reference=False)
                except (ValueError, TypeError):
                    pass
        elif self.instance.pk:
            # En édition, pré-remplir les queryset selon l'instance
            if self.instance.ecole:
                self.fields['niveau'].queryset = Niveau.objects.filter(ecole=self.instance.ecole, est_reference=False)
            if self.instance.niveau:
                self.fields['classe'].queryset = Classe.objects.filter(niveau=self.instance.niveau, est_reference=False)

    def clean(self):
        cleaned_data = super().clean()
        ecole = cleaned_data.get('ecole')
        niveau = cleaned_data.get('niveau')
        classe = cleaned_data.get('classe')
        # Vérifications de cohérence
        if classe and niveau and classe.niveau != niveau:
            self.add_error('classe', "La classe sélectionnée ne correspond pas au niveau choisi.")
        if classe and ecole and classe.ecole != ecole:
            self.add_error('classe', "La classe sélectionnée n'appartient pas à l'école choisie.")
        return cleaned_data


class BulletinForm(forms.ModelForm):
    class Meta:
        model = Bulletin
        fields = ['eleve', 'annee_scolaire', 'fichier', 'description']
        widgets = {
            'eleve': forms.Select(attrs={'class': 'form-select'}),
            'annee_scolaire': forms.Select(attrs={'class': 'form-select'}),
            'fichier': forms.FileInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Description (facultatif)'}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        if user:
            if user.est_enseignant() and user.classe_affectation:
                self.fields['eleve'].queryset = Eleve.objects.filter(classe=user.classe_affectation)
            elif user.est_agent() and user.ecole_affectation:
                self.fields['eleve'].queryset = Eleve.objects.filter(ecole=user.ecole_affectation)
            elif user.est_inspecteur() and user.ecole_affectation:
                self.fields['eleve'].queryset = Eleve.objects.filter(ecole=user.ecole_affectation)
            # Admin voit tous