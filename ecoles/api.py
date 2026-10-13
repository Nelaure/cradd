from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from .models import Niveau, Classe, Domaine, Cours
from eleves.models import Eleve

@login_required
def api_get_niveaux(request):
    ecole_id = request.GET.get('ecole_id')
    if not ecole_id:
        return JsonResponse({'error': 'ecole_id requis'}, status=400)
    niveaux = Niveau.objects.filter(ecole_id=ecole_id).values('id', 'nom')
    return JsonResponse({'niveaux': list(niveaux)})

@login_required
def api_get_classes(request):
    niveau_id = request.GET.get('niveau_id')
    if not niveau_id:
        return JsonResponse({'error': 'niveau_id requis'}, status=400)
    classes = Classe.objects.filter(niveau_id=niveau_id).values('id', 'nom')
    return JsonResponse({'classes': list(classes)})

@login_required
def api_get_domaines(request):
    ecole_id = request.GET.get('ecole_id')
    if not ecole_id:
        return JsonResponse({'error': 'ecole_id requis'}, status=400)
    domaines = Domaine.objects.filter(ecole_id=ecole_id).values('id', 'nom')
    return JsonResponse({'domaines': list(domaines)})

@login_required
def api_get_cours(request):
    classe_id = request.GET.get('classe_id')
    if not classe_id:
        return JsonResponse({'error': 'classe_id requis'}, status=400)
    cours = Cours.objects.filter(classe_id=classe_id).values('id', 'nom', 'code')
    return JsonResponse({'cours': list(cours)})

@login_required
def api_get_eleves(request):
    classe_id = request.GET.get('classe_id')
    if not classe_id:
        return JsonResponse({'error': 'classe_id requis'}, status=400)
    eleves = Eleve.objects.filter(classe_id=classe_id).values('id', 'nom', 'prenom', 'matricule')
    return JsonResponse({'eleves': list(eleves)})