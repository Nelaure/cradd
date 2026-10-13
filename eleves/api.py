from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from .models import Eleve

@login_required
def api_recherche_eleve(request):
    q = request.GET.get('q', '')
    eleves = Eleve.objects.filter(
        models.Q(nom__icontains=q) |
        models.Q(postnom__icontains=q) |
        models.Q(prenom__icontains=q) |
        models.Q(matricule__icontains=q)
    )[:20]
    data = [{'id': e.id, 'nom_complet': e.get_nom_complet(), 'matricule': e.matricule} for e in eleves]
    return JsonResponse({'eleves': data})