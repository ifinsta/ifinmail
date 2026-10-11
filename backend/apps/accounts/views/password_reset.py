"""Password reset views using Django's built-in auth flows."""

from django.contrib.auth.views import (
    PasswordResetCompleteView,
    PasswordResetConfirmView,
    PasswordResetDoneView,
    PasswordResetView,
)
from django.http import HttpResponse

from backend.services.audit import AuditService


class CustomPasswordResetView(PasswordResetView):
    template_name = 'admin/password_reset_form.html'
    email_template_name = 'admin/password_reset_email.html'
    subject_template_name = 'admin/password_reset_subject.txt'
    success_url = '/accounts/password-reset/done/'

    def form_valid(self, form) -> HttpResponse:
        AuditService.record(
            action='password_reset_requested',
            user=(form.cleaned_data.get('email') or '').strip().lower(),
            detail='reset link requested',
        )
        return super().form_valid(form)


class CustomPasswordResetDoneView(PasswordResetDoneView):
    template_name = 'admin/password_reset_done.html'


class CustomPasswordResetConfirmView(PasswordResetConfirmView):
    template_name = 'admin/password_reset_confirm.html'
    success_url = '/accounts/password-reset/complete/'

    def form_valid(self, form) -> HttpResponse:
        response = super().form_valid(form)
        AuditService.record(
            action='password_reset_completed',
            user=getattr(self.user, 'email', ''),
            detail='password changed via reset link',
        )
        return response


class CustomPasswordResetCompleteView(PasswordResetCompleteView):
    template_name = 'admin/password_reset_complete.html'


password_reset = CustomPasswordResetView.as_view()
password_reset_done = CustomPasswordResetDoneView.as_view()
password_reset_confirm = CustomPasswordResetConfirmView.as_view()
password_reset_complete = CustomPasswordResetCompleteView.as_view()
