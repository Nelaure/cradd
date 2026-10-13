from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from .models import Utilisateur

@login_required
def api_utilisateurs_list(request):
    users = Utilisateur.objects.values('id', 'username', 'nom', 'prenom', 'role')
    return JsonResponse({'users': list(users)})

@login_required
def api_utilisateur_detail(request, pk):
    try:
        user = Utilisateur.objects.get(pk=pk)
        data = {
            'id': user.id,
            'username': user.username,
            'nom': user.nom,
            'postnom': user.postnom,
            'prenom': user.prenom,
            'email': user.email,
            'role': user.role,
            'ecole_affectation': user.ecole_affectation_id,
            'est_actif': user.est_actif
        }
        return JsonResponse(data)
    except Utilisateur.DoesNotExist:
        return JsonResponse({'error': 'Utilisateur non trouvé'}, status=404)