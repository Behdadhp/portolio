from django.test import TestCase, Client
from django.urls import reverse

from .forms import (
    ChangePasswordForm,
    EditProfileForm,
    LoginForm,
    RegisterForm,
    validate_password_strength,
)
from .models import User

# ── Model tests ──────────────────────────────────────────────


class UserModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="test@example.com",
            password="Test1234",
            first_name="Alice",
            last_name="Smith",
            birthdate="1990-05-20",
        )

    def test_user_has_uuid_pk(self):
        self.assertIsNotNone(self.user.pk)
        self.assertEqual(str(self.user.pk).count("-"), 4)

    def test_str_returns_email(self):
        self.assertEqual(str(self.user), "test@example.com")

    def test_password_is_hashed(self):
        self.assertNotEqual(self.user.password, "Test1234")
        self.assertTrue(self.user.check_password("Test1234"))

    def test_email_is_unique(self):
        with self.assertRaises(Exception):
            User.objects.create_user(
                email="test@example.com",
                password="Other123",
                first_name="Bob",
                last_name="Jones",
                birthdate="1991-01-01",
            )

    def test_username_field_is_email(self):
        self.assertEqual(User.USERNAME_FIELD, "email")

    def test_create_superuser(self):
        admin = User.objects.create_superuser(
            email="admin@example.com",
            password="Admin123",
            first_name="Admin",
            last_name="User",
            birthdate="1985-01-01",
        )
        self.assertTrue(admin.is_staff)
        self.assertTrue(admin.is_superuser)

    def test_create_user_without_email_raises(self):
        with self.assertRaises(ValueError):
            User.objects.create_user(
                email="",
                password="Test1234",
                first_name="No",
                last_name="Email",
                birthdate="1990-01-01",
            )


# ── Password validation tests ───────────────────────────────


class PasswordValidationTest(TestCase):
    def test_valid_password(self):
        self.assertEqual(validate_password_strength("Abcdef1234"), [])

    def test_too_short(self):
        errors = validate_password_strength("Ab1")
        self.assertTrue(any("8 characters" in e for e in errors))

    def test_no_uppercase(self):
        errors = validate_password_strength("abcdef123")
        self.assertTrue(any("capital letter" in e for e in errors))

    def test_no_lowercase(self):
        errors = validate_password_strength("ABCDEF123")
        self.assertTrue(any("lowercase" in e for e in errors))

    def test_no_number(self):
        errors = validate_password_strength("Abcdefgh")
        self.assertTrue(any("number" in e for e in errors))

    def test_all_rules_fail(self):
        errors = validate_password_strength("aaa")
        self.assertEqual(len(errors), 3)  # short, no uppercase, no number


# ── Form tests ───────────────────────────────────────────────


class RegisterFormTest(TestCase):
    def _form_data(self, **overrides):
        data = {
            "first_name": "Alice",
            "last_name": "Smith",
            "email": "alice@example.com",
            "birthdate": "1990-05-20",
            "password": "Abcdef12",
            "confirm_password": "Abcdef12",
        }
        data.update(overrides)
        return data

    def test_valid_form(self):
        form = RegisterForm(data=self._form_data())
        self.assertTrue(form.is_valid())

    def test_passwords_do_not_match(self):
        form = RegisterForm(data=self._form_data(confirm_password="Different1"))
        self.assertFalse(form.is_valid())

    def test_weak_password_rejected(self):
        form = RegisterForm(
            data=self._form_data(password="weak", confirm_password="weak")
        )
        self.assertFalse(form.is_valid())

    def test_missing_email(self):
        form = RegisterForm(data=self._form_data(email=""))
        self.assertFalse(form.is_valid())


class LoginFormTest(TestCase):
    def test_valid_form(self):
        form = LoginForm(data={"email": "a@b.com", "password": "pass"})
        self.assertTrue(form.is_valid())

    def test_invalid_email(self):
        form = LoginForm(data={"email": "not-an-email", "password": "pass"})
        self.assertFalse(form.is_valid())


class EditProfileFormTest(TestCase):
    def test_valid_form(self):
        form = EditProfileForm(
            data={
                "first_name": "Alice",
                "last_name": "Smith",
                "email": "alice@example.com",
                "birthdate": "1990-05-20",
            }
        )
        self.assertTrue(form.is_valid())


class ChangePasswordFormTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="test@example.com",
            password="OldPass123",
            first_name="Test",
            last_name="User",
            birthdate="1990-01-01",
        )

    def test_valid_change(self):
        form = ChangePasswordForm(
            data={
                "current_password": "OldPass123",
                "new_password": "NewPass456",
                "confirm_new_password": "NewPass456",
            },
            user=self.user,
        )
        self.assertTrue(form.is_valid())

    def test_wrong_current_password(self):
        form = ChangePasswordForm(
            data={
                "current_password": "WrongPass1",
                "new_password": "NewPass456",
                "confirm_new_password": "NewPass456",
            },
            user=self.user,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("current_password", form.errors)

    def test_new_passwords_do_not_match(self):
        form = ChangePasswordForm(
            data={
                "current_password": "OldPass123",
                "new_password": "NewPass456",
                "confirm_new_password": "Different1",
            },
            user=self.user,
        )
        self.assertFalse(form.is_valid())

    def test_weak_new_password(self):
        form = ChangePasswordForm(
            data={
                "current_password": "OldPass123",
                "new_password": "weak",
                "confirm_new_password": "weak",
            },
            user=self.user,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("new_password", form.errors)


# ── View tests ───────────────────────────────────────────────


class LoginViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            email="test@example.com",
            password="Test1234",
            first_name="Test",
            last_name="User",
            birthdate="1990-01-01",
        )

    def test_login_page_renders(self):
        response = self.client.get(reverse("login"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "accounts/login.html")

    def test_login_success_redirects_to_dashboard(self):
        response = self.client.post(
            reverse("login"),
            {"email": "test@example.com", "password": "Test1234"},
        )
        self.assertRedirects(response, reverse("dashboard"))

    def test_login_wrong_password_shows_error(self):
        response = self.client.post(
            reverse("login"),
            {"email": "test@example.com", "password": "WrongPass1"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Email or password is wrong.")

    def test_login_nonexistent_user_shows_error(self):
        response = self.client.post(
            reverse("login"),
            {"email": "nobody@example.com", "password": "Test1234"},
        )
        self.assertContains(response, "Email or password is wrong.")

    def test_authenticated_user_redirects_to_dashboard(self):
        self.client.login(username="test@example.com", password="Test1234")
        response = self.client.get(reverse("login"))
        self.assertRedirects(response, reverse("dashboard"))


class RegisterViewTest(TestCase):
    def setUp(self):
        self.client = Client()

    def test_register_page_renders(self):
        response = self.client.get(reverse("register"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "accounts/register.html")

    def test_register_creates_user_and_redirects(self):
        response = self.client.post(
            reverse("register"),
            {
                "first_name": "Alice",
                "last_name": "Smith",
                "email": "alice@example.com",
                "birthdate": "1990-05-20",
                "password": "Abcdef12",
                "confirm_password": "Abcdef12",
            },
        )
        self.assertRedirects(response, reverse("dashboard"))
        self.assertTrue(User.objects.filter(email="alice@example.com").exists())

    def test_register_logs_user_in(self):
        self.client.post(
            reverse("register"),
            {
                "first_name": "Alice",
                "last_name": "Smith",
                "email": "alice@example.com",
                "birthdate": "1990-05-20",
                "password": "Abcdef12",
                "confirm_password": "Abcdef12",
            },
        )
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)

    def test_register_weak_password_fails(self):
        response = self.client.post(
            reverse("register"),
            {
                "first_name": "Alice",
                "last_name": "Smith",
                "email": "alice@example.com",
                "birthdate": "1990-05-20",
                "password": "weak",
                "confirm_password": "weak",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(email="alice@example.com").exists())

    def test_register_duplicate_email_fails(self):
        User.objects.create_user(
            email="alice@example.com",
            password="Abcdef12",
            first_name="Alice",
            last_name="Smith",
            birthdate="1990-05-20",
        )
        response = self.client.post(
            reverse("register"),
            {
                "first_name": "Alice2",
                "last_name": "Smith2",
                "email": "alice@example.com",
                "birthdate": "1991-01-01",
                "password": "Abcdef12",
                "confirm_password": "Abcdef12",
            },
        )
        self.assertEqual(response.status_code, 200)


class DashboardViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            email="test@example.com",
            password="Test1234",
            first_name="Test",
            last_name="User",
            birthdate="1990-01-01",
        )

    def test_dashboard_requires_login(self):
        response = self.client.get(reverse("dashboard"))
        self.assertRedirects(
            response, f"{reverse('login')}?next={reverse('dashboard')}"
        )

    def test_dashboard_shows_user_info(self):
        self.client.login(username="test@example.com", password="Test1234")
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Test")
        self.assertContains(response, "User")
        self.assertContains(response, "test@example.com")


class EditProfileViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            email="test@example.com",
            password="Test1234",
            first_name="Test",
            last_name="User",
            birthdate="1990-01-01",
        )
        self.client.login(username="test@example.com", password="Test1234")

    def test_edit_profile_page_renders(self):
        response = self.client.get(reverse("edit_profile"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "accounts/edit_profile.html")

    def test_update_profile_info(self):
        response = self.client.post(
            reverse("edit_profile"),
            {
                "save_profile": "1",
                "first_name": "Updated",
                "last_name": "Name",
                "email": "test@example.com",
                "birthdate": "1990-01-01",
            },
        )
        self.assertRedirects(response, reverse("edit_profile"))
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Updated")
        self.assertEqual(self.user.last_name, "Name")

    def test_change_password(self):
        response = self.client.post(
            reverse("edit_profile"),
            {
                "change_password": "1",
                "current_password": "Test1234",
                "new_password": "NewPass456",
                "confirm_new_password": "NewPass456",
            },
        )
        self.assertRedirects(response, reverse("edit_profile"))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("NewPass456"))

    def test_change_password_wrong_current(self):
        response = self.client.post(
            reverse("edit_profile"),
            {
                "change_password": "1",
                "current_password": "WrongPass1",
                "new_password": "NewPass456",
                "confirm_new_password": "NewPass456",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("Test1234"))

    def test_edit_profile_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse("edit_profile"))
        self.assertEqual(response.status_code, 302)


class LogoutViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            email="test@example.com",
            password="Test1234",
            first_name="Test",
            last_name="User",
            birthdate="1990-01-01",
        )

    def test_logout_redirects_to_login(self):
        self.client.login(username="test@example.com", password="Test1234")
        response = self.client.get(reverse("logout"))
        self.assertRedirects(response, reverse("login"))

    def test_logout_clears_session(self):
        self.client.login(username="test@example.com", password="Test1234")
        self.client.get(reverse("logout"))
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 302)
