from decimal import Decimal
from .models import ResultatCycle, ResultatAnnuel, EvaluationResultat

def recalculer_resultats_eleve(eleve, annee):
    """
    Recalcule les résultats cycle et annuel pour un élève donné.
    """
    resultats = EvaluationResultat.objects.filter(eleve=eleve, annee_scolaire=annee)
    cycles_data = {}
    for r in resultats:
        key = (r.cours.id, r.evaluation_config.cycle_num)
        if key not in cycles_data:
            cycles_data[key] = {'total_obtenus': 0, 'total_possibles': 0}
        cycles_data[key]['total_obtenus'] += float(r.points_obtenus)
        cycles_data[key]['total_possibles'] += r.evaluation_config.points_max

    for (cours_id, cycle_num), data in cycles_data.items():
        total_obtenus = Decimal(str(data['total_obtenus']))
        total_possibles = Decimal(str(data['total_possibles']))
        pourcentage = (total_obtenus / total_possibles * 100) if total_possibles > 0 else 0
        moyenne_sur_20 = (total_obtenus / total_possibles * 20) if total_possibles > 0 else 0
        ResultatCycle.objects.update_or_create(
            eleve=eleve,
            cours_id=cours_id,
            annee_scolaire=annee,
            cycle_num=cycle_num,
            defaults={
                'total_points_obtenus': total_obtenus,
                'total_points_possibles': total_possibles,
                'pourcentage': pourcentage,
                'moyenne_sur_20': moyenne_sur_20,
            }
        )

    resultat_annuel, created = ResultatAnnuel.objects.get_or_create(
        eleve=eleve,
        annee_scolaire=annee
    )
    resultat_annuel.recalculer()


# ===================== CONTEXT PROCESSOR POUR LA CORBEILLE =====================
def trash_count(request):
    """
    Context processor pour afficher le nombre d'éléments dans la corbeille.
    """
    from .models import Ecole, Niveau, Classe, Domaine, Cours
    from eleves.models import Eleve

    total = 0
    for model in [Ecole, Niveau, Classe, Domaine, Cours, Eleve]:
        # all_objects est le manager qui inclut les éléments supprimés (si le modèle a été étendu)
        if hasattr(model, 'all_objects'):
            total += model.all_objects.filter(deleted_at__isnull=False).count()
    return {'trash_count': total}