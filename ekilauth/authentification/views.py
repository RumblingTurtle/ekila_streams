import threading

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.shortcuts import get_object_or_404
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from rest_framework import status
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.serializers import TokenBlacklistSerializer
from rest_framework_simplejwt.views import TokenBlacklistView
from rest_framework_simplejwt.views import TokenObtainPairView

from ekilauth.authentification.email import MailManagement
from ekilauth.authentification.permissions import IsConfirmedUser
from ekilauth.authentification.serializers import ObtainTokenSerializer
from ekilauth.authentification.serializers import PasswordResetConfirmSerializer
from ekilauth.authentification.serializers import ResendActivationCode
from ekilauth.authentification.serializers import SendPasswordResetEmailSerializer
from ekilauth.authentification.serializers import UserChangePasswordSerializer
from ekilauth.authentification.serializers import UserProfileSerializer
from ekilauth.authentification.serializers import UserRegistrationSerializer
from ekilauth.authentification.serializers import UserSerializer
from ekilauth.authentification.serializers import VerificationEmailSerializer


class ObtainTokenView(TokenObtainPairView):
    serializer_class = ObtainTokenSerializer


class EkilAuthViewSet(viewsets.GenericViewSet):
    queryset = get_user_model().objects.all()
    serializer_class = UserSerializer
    permission_classes = ()

    def get_serializer_class(self):
        action = self.action
        match action:
            case "register":
                return UserRegistrationSerializer
            case "change_password":
                return UserChangePasswordSerializer
            case "reset_password":
                return SendPasswordResetEmailSerializer
            case "reset_password_confirm":
                return PasswordResetConfirmSerializer
            case "verify_email":
                return VerificationEmailSerializer
            case "me":
                return UserProfileSerializer
            case "resend_code_activation":
                return ResendActivationCode
            case "logout":
                return TokenBlacklistSerializer
            case _:
                return self.serializer_class

    @action(
        detail=False,
        methods=["POST"],
        permission_classes=(AllowAny,),
    )
    def register(self, request: Request) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        sending_email_thread = threading.Thread(
            target=MailManagement.send_code_for_verification,
            args=(serializer.data["email"],),
        )
        sending_email_thread.start()
        return Response(
            {
                "username": user.username,
                "email": user.email,
                "message": "Registration Successful. "
                f"Please confirm your email with code send to your email {user.email}",
            },
            status=status.HTTP_201_CREATED,
        )

    @action(
        detail=False,
        methods=["POST"],
        permission_classes=(AllowAny,),
        url_path="resend-activation-code",
    )
    def resend_code_activation(self, request: Request) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            MailManagement.send_code_for_verification(serializer.data["email"])
        except TimeoutError:
            return Response(
                {"message": "An error occurred while sending email"},
                status=status.HTTP_408_REQUEST_TIMEOUT,
            )
        return Response(
            {"message": "Code send successfully "},
            status=status.HTTP_200_OK,
        )

    @action(
        detail=False,
        methods=["POST"],
        permission_classes=(IsAuthenticated, IsConfirmedUser),
        url_path="password/change",
    )
    def change_password(self, request: Request) -> Response:
        serializer = self.get_serializer(
            data=request.data, context={"user": request.user}
        )
        serializer.is_valid(raise_exception=True)
        return Response(
            {"message": "Password Changed Successfully"}, status=status.HTTP_200_OK
        )

    @action(
        detail=False,
        methods=["POST"],
        permission_classes=(AllowAny,),
        url_path="password/reset",
    )
    def reset_password(self, request: Request) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.data["email"]
        user = get_object_or_404(get_user_model(), email=email)
        uid = urlsafe_base64_encode(force_bytes(user.id))
        token = PasswordResetTokenGenerator().make_token(user)
        link = settings.FRONT_END_URL + uid + "/" + token
        data = {
            "subject": "Reset Your Password",
            "to_email": user.email,
            "link": link,
        }

        threading.Thread(
            target=MailManagement.send_email,
            args=(data,),
        ).start()

        return Response(
            {"message": "Password Reset link send. Please check your Email"},
            status=status.HTTP_200_OK,
        )

    @action(
        detail=False,
        methods=["POST"],
        permission_classes=(AllowAny,),
        url_path="password/reset/confirm",
    )
    def reset_password_confirm(self, request: Request) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(
            {"message": "Password Reset Successfully"}, status=status.HTTP_200_OK
        )

    @action(
        detail=False,
        methods=["POST"],
        permission_classes=(AllowAny,),
        url_path="verify-email",
    )
    def verify_email(self, request: Request) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.data["email"]
        confirm_number = serializer.data["confirm_number"]
        user_obj = get_object_or_404(
            get_user_model(),
            email=email,
            confirm_number=confirm_number,
            is_confirmed=False,
        )
        user_obj.is_confirmed = True
        user_obj.save()
        return Response(
            {"message": "Email verified. You can login now"},
            status=status.HTTP_200_OK,
        )

    @action(
        detail=False,
        methods=("GET",),
        authentication_classes=(JWTAuthentication,),
        permission_classes=(IsAuthenticated, IsConfirmedUser),
    )
    def me(self, request: Request) -> Response:
        serializer = self.get_serializer(instance=request.user)
        return Response(serializer.data)

    @action(detail=False, methods=("POST",), permission_classes=(IsAuthenticated,))
    def logout(self, request: Request) -> Response:
        logout_view = TokenBlacklistView.as_view()
        response = logout_view(request._request)
        return response
