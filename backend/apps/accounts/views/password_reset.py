"""Password reset views using Django's built-in auth flows."""

from django.contrib.auth.views import (
    PasswordResetCompleteView,
    PasswordResetConfirmView,
    PasswordResetDoneView,
    PasswordResetView,
)
from django.http import HttpResponse

from backend.apps.core.platform.services.audit import AuditService
from backend.config.branding import email_brand_context


class CustomPasswordResetView(PasswordResetView):
    template_name = 'admin/password_reset_form.html'
    # Plain-text body plus the branded HTML alternative (Django sends both when
    # html_email_template_name is set).
    email_template_name = 'admin/password_reset_email.txt'
    html_email_template_name = 'admin/password_reset_email.html'
    subject_template_name = 'admin/password_reset_subject.txt'
    success_url = '/accounts/password-reset/done/'

    def form_valid(self, form) -> HttpResponse:
        # Django renders the email without request-context processors; inject the
        # brand and an absolute logo URL so the email carries the custom logo.
        self.extra_email_context = email_brand_context(self.request.build_absolute_uri)
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
