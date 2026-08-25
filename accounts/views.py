import logging
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, authenticate, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone
from django.db.models import Q
from .models import Utilisateur, AuditLog
from .forms import (
    UtilisateurCreationForm, UtilisateurChangeForm, 
    PasswordResetRequestForm, PasswordResetVerifyForm
)
from ecoles.models import Ecole, Niveau, Classe
from eleves.models import Eleve

logger = logging.getLogger(__name__)

# ===================== FONCTIONS UTILITAIRES =====================

def log_audit(user, action, model_name=None, object_id=None, object_repr=None, 
              changes=None, ip_address=None, user_agent=None, success=True, message=None):
    try:
        AuditLog.objects.create(
            utilisateur=user,
            action=action,
            model_name=model_name,
            object_id=str(object_id) if object_id else None,
            object_repr=object_repr or '',
            changes=changes or {},
            ip_address=ip_address,
            user_agent=user_agent,
            success=success,
            message=message
        )
    except Exception as e:
        logger.error(f"Erreur lors de l'enregistrement du journal d'activité : {e}")

def get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip

# ===================== AUTHENTIFICATION =====================

def login_view(request):
    if request.user.is_authenticated:
        return redirect('ecoles:dashboard')
    
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        
        ip = get_client_ip(request)
        user_agent = request.META.get('HTTP_USER_AGENT', '')
        
        if user and user.est_actif:
            login(request, user)
            log_audit(
                user=user,
                action=AuditLog.ActionType.LOGIN,
                ip_address=ip,
                user_agent=user_agent,
                success=True,
                message=f"Connexion depuis {ip}"
            )
            # Redirection selon le rôle
            if user.est_editeur():
                return redirect('actualites:dashboard')
            else:
                return redirect(request.GET.get('next', 'ecoles:dashboard'))
        else:
            if user:
                log_audit(
                    user=user,
                    action=AuditLog.ActionType.LOGIN_FAILED,
                    ip_address=ip,
                    user_agent=user_agent,
                    success=False,
                    message=f"Tentative de connexion échouée depuis {ip}"
                )
            messages.error(request, 'Identifiants incorrects ou compte inactif.')
    
    return render(request, 'accounts/login.html')


@login_required
def logout_view(request):
    ip = get_client_ip(request)
    user_agent = request.META.get('HTTP_USER_AGENT', '')
    log_audit(
        user=request.user,
        action=AuditLog.ActionType.LOGOUT,
        ip_address=ip,
        user_agent=user_agent,
        success=True,
        message=f"Déconnexion depuis {ip}"
    )
    logout(request)
    messages.info(request, 'Vous avez été déconnecté avec succès.')
    return redirect('ecoles:index')


@login_required
def profile_view(request):
    return render(request, 'accounts/profile.html', {'user': request.user})


@login_required
def change_password_view(request):
    if request.method == 'POST':
        old_password = request.POST.get('old_password')
        new_password = request.POST.get('new_password')
        confirm_password = request.POST.get('confirm_password')
        
        if not request.user.check_password(old_password):
            messages.error(request, 'Mot de passe actuel incorrect.')
        elif new_password != confirm_password:
            messages.error(request, 'Les nouveaux mots de passe ne correspondent pas.')
        elif len(new_password) < 8:
            messages.error(request, 'Le mot de passe doit contenir au moins 8 caractères.')
        else:
            request.user.set_password(new_password)
            request.user.save()
            update_session_auth_hash(request, request.user)
            
            ip = get_client_ip(request)
            user_agent = request.META.get('HTTP_USER_AGENT', '')
            log_audit(
                user=request.user,
                action=AuditLog.ActionType.PASSWORD_CHANGE,
                ip_address=ip,
                user_agent=user_agent,
                success=True,
                message="Changement de mot de passe"
            )
            messages.success(request, 'Votre mot de passe a été modifié avec succès.')
            return redirect('accounts:profile')
    
    return render(request, 'accounts/change_password.html')

# ===================== RÉINITIALISATION MOT DE PASSE =====================

def password_reset_request_view(request):
    if request.user.is_authenticated:
        return redirect('ecoles:dashboard')
    
    if request.method == 'POST':
        form = PasswordResetRequestForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data['email']
            try:
                user = Utilisateur.objects.get(email=email)
                code = user.generate_reset_code()
                
                subject = 'Réinitialisation de votre mot de passe - Cradd'
                message = f"""
                Bonjour {user.get_full_name()},
                
                Vous avez demandé la réinitialisation de votre mot de passe.
                
                Votre code de réinitialisation est : {code}
                
                Ce code est valable 15 minutes.
                
                Si vous n'êtes pas à l'origine de cette demande, ignorez cet email.
                
                Cordialement,
                L'équipe Cradd
                """
                
                try:
                    send_mail(
                        subject,
                        message,
                        settings.DEFAULT_FROM_EMAIL,
                        [email],
                        fail_silently=False,
                    )
                    ip = get_client_ip(request)
                    user_agent = request.META.get('HTTP_USER_AGENT', '')
                    log_audit(
                        user=user,
                        action=AuditLog.ActionType.PASSWORD_RESET,
                        ip_address=ip,
                        user_agent=user_agent,
                        success=True,
                        message=f"Demande de réinitialisation envoyée à {email}"
                    )
                    request.session['reset_email'] = email
                    messages.success(
                        request, 
                        f'Un code de réinitialisation a été envoyé à {email}. '
                        'Veuillez vérifier votre boîte mail (pensez à vérifier les spams).'
                    )
                    return redirect('accounts:password_reset_verify')
                    
                except Exception as e:
                    logger.error(f"Erreur SMTP lors de l'envoi à {email} : {str(e)}")
                    if settings.DEBUG:
                        messages.error(
                            request, 
                            f"Erreur d'envoi : {str(e)}. Vérifiez votre configuration SMTP."
                        )
                    else:
                        messages.error(
                            request, 
                            "Une erreur est survenue lors de l'envoi de l'email. "
                            "Veuillez réessayer plus tard ou contacter l'administrateur."
                        )
                    
            except Utilisateur.DoesNotExist:
                messages.success(
                    request, 
                    'Si un compte existe avec cet email, '
                    'un code de réinitialisation vous a été envoyé.'
                )
                return redirect('accounts:password_reset_verify')
        else:
            messages.error(request, 'Veuillez corriger les erreurs du formulaire.')
    else:
        form = PasswordResetRequestForm()
    
    return render(request, 'accounts/password_reset_request.html', {'form': form})


def password_reset_verify_view(request):
    if request.user.is_authenticated:
        return redirect('ecoles:dashboard')
    
    email = request.session.get('reset_email')
    
    if request.method == 'POST':
        form = PasswordResetVerifyForm(request.POST)
        if form.is_valid():
            code = form.cleaned_data['code']
            new_password = form.cleaned_data['new_password']
            
            try:
                user = Utilisateur.objects.get(
                    reset_code=code,
                    reset_code_used=False
                )
                
                if user.verify_reset_code(code):
                    user.set_password(new_password)
                    user.reset_code = None
                    user.reset_code_created_at = None
                    user.reset_code_used = True
                    user.save()
                    
                    ip = get_client_ip(request)
                    user_agent = request.META.get('HTTP_USER_AGENT', '')
                    log_audit(
                        user=user,
                        action=AuditLog.ActionType.PASSWORD_RESET,
                        ip_address=ip,
                        user_agent=user_agent,
                        success=True,
                        message="Mot de passe réinitialisé avec succès"
                    )
                    
                    messages.success(
                        request, 
                        'Votre mot de passe a été réinitialisé avec succès. '
                        'Vous pouvez maintenant vous connecter.'
                    )
                    
                    if 'reset_email' in request.session:
                        del request.session['reset_email']
                    
                    return redirect('accounts:login')
                else:
                    messages.error(request, 'Code invalide ou expiré.')
                    
            except Utilisateur.DoesNotExist:
                messages.error(request, 'Code invalide ou expiré.')
        else:
            messages.error(request, 'Veuillez corriger les erreurs ci-dessous.')
    else:
        form = PasswordResetVerifyForm()
    
    return render(request, 'accounts/password_reset_verify.html', {
        'form': form,
        'email': email
    })

# ===================== GESTION DES UTILISATEURS =====================

@login_required
def user_list_view(request):
    if not request.user.est_administrateur():
        messages.error(request, 'Accès non autorisé.')
        return redirect('ecoles:dashboard')
    
    users = Utilisateur.objects.all().order_by('-date_creation')
    paginator = Paginator(users, 20)
    page = request.GET.get('page')
    users = paginator.get_page(page)
    
    return render(request, 'accounts/user_list.html', {'users': users})


@login_required
def user_create_view(request):
    if not request.user.est_administrateur():
        messages.error(request, 'Accès non autorisé.')
        return redirect('ecoles:dashboard')
    
    if request.method == 'POST':
        form = UtilisateurCreationForm(request.POST, user=request.user)
        if form.is_valid():
            user = form.save()
            
            ip = get_client_ip(request)
            user_agent = request.META.get('HTTP_USER_AGENT', '')
            log_audit(
                user=request.user,
                action=AuditLog.ActionType.CREATE,
                model_name=AuditLog.ModelName.UTILISATEUR,
                object_id=user.id,
                object_repr=str(user),
                ip_address=ip,
                user_agent=user_agent,
                success=True,
                message=f"Création de l'utilisateur {user.username}"
            )
            
            messages.success(request, f"Utilisateur '{user.username}' créé avec succès.")
            return redirect('accounts:user_list')
        else:
            messages.error(request, 'Veuillez corriger les erreurs ci-dessous.')
    else:
        form = UtilisateurCreationForm(user=request.user)
    
    return render(request, 'accounts/user_form.html', {
        'form': form,
        'title': 'Créer un utilisateur'
    })


@login_required
def user_edit_view(request, pk):
    if not request.user.est_administrateur():
        messages.error(request, 'Accès non autorisé.')
        return redirect('ecoles:dashboard')
    
    user = get_object_or_404(Utilisateur, pk=pk)
    
    if request.method == 'POST':
        form = UtilisateurChangeForm(request.POST, instance=user, user=request.user)
        if form.is_valid():
            form.save()
            
            ip = get_client_ip(request)
            user_agent = request.META.get('HTTP_USER_AGENT', '')
            log_audit(
                user=request.user,
                action=AuditLog.ActionType.UPDATE,
                model_name=AuditLog.ModelName.UTILISATEUR,
                object_id=user.id,
                object_repr=str(user),
                ip_address=ip,
                user_agent=user_agent,
                success=True,
                message=f"Modification de l'utilisateur {user.username}"
            )
            
            messages.success(request, f"Utilisateur '{user.username}' modifié avec succès.")
            return redirect('accounts:user_list')
        else:
            messages.error(request, 'Veuillez corriger les erreurs ci-dessous.')
    else:
        form = UtilisateurChangeForm(instance=user, user=request.user)
    
    return render(request, 'accounts/user_form.html', {
        'form': form,
        'title': 'Modifier un utilisateur'
    })


@login_required
def user_delete_view(request, pk):
    if not request.user.est_administrateur():
        messages.error(request, 'Accès non autorisé.')
        return redirect('ecoles:dashboard')
    
    user = get_object_or_404(Utilisateur, pk=pk)
    
    if user.is_superuser:
        messages.error(request, "Cet utilisateur est un administrateur principal et ne peut pas être supprimé.")
        return redirect('accounts:user_list')
    
    if user == request.user:
        messages.error(request, "Vous ne pouvez pas supprimer votre propre compte.")
        return redirect('accounts:user_list')
    
    if request.method == 'POST':
        username = user.username
        
        ip = get_client_ip(request)
        user_agent = request.META.get('HTTP_USER_AGENT', '')
        log_audit(
            user=request.user,
            action=AuditLog.ActionType.DELETE,
            model_name=AuditLog.ModelName.UTILISATEUR,
            object_id=user.id,
            object_repr=str(user),
            ip_address=ip,
            user_agent=user_agent,
            success=True,
            message=f"Suppression de l'utilisateur {username}"
        )
        
        user.delete()
        messages.success(request, f"Utilisateur '{username}' supprimé avec succès.")
        return redirect('accounts:user_list')
    
    return render(request, 'accounts/user_confirm_delete.html', {'user': user})


# ===================== JOURNAL D'ACTIVITÉ =====================

@login_required
def audit_log_view(request):
    if not request.user.est_administrateur():
        messages.error(request, 'Accès non autorisé.')
        return redirect('ecoles:dashboard')
    
    logs = AuditLog.objects.select_related('utilisateur').all()
    
    action = request.GET.get('action')
    user_id = request.GET.get('user')
    model = request.GET.get('model')
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    
    if action:
        logs = logs.filter(action=action)
    if user_id:
        logs = logs.filter(utilisateur_id=user_id)
    if model:
        logs = logs.filter(model_name=model)
    if date_from:
        logs = logs.filter(timestamp__date__gte=date_from)
    if date_to:
        logs = logs.filter(timestamp__date__lte=date_to)
    
    paginator = Paginator(logs, 50)
    page = request.GET.get('page')
    logs = paginator.get_page(page)
    
    context = {
        'logs': logs,
        'users': Utilisateur.objects.all().order_by('username'),
        'actions': AuditLog.ActionType.choices,
        'models': AuditLog.ModelName.choices,
        'selected_action': action,
        'selected_user': user_id,
        'selected_model': model,
        'selected_date_from': date_from,
        'selected_date_to': date_to,
    }
    
    return render(request, 'accounts/audit_log.html', context)