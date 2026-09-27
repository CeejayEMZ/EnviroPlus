from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from .models import SensorNode
from django import forms
from .models import Product

User = get_user_model()


class CustomAuthenticationForm(AuthenticationForm):
    """Login form with Bootstrap styling and approval checking."""
    username = forms.CharField(
        label="Username or Email",
        max_length=255,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter your username or email',
            'autocomplete': 'username',
        })
    )
    password = forms.CharField(
        label="Password",
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter your password',
            'autocomplete': 'current-password',
        })
    )
    
    def clean(self):
        """Validate user is active and approved."""
        cleaned_data = super().clean()
        username = cleaned_data.get('username')
        password = cleaned_data.get('password')
        
        if username and password:
            try:
                user = User.objects.get(username=username)
                if not user.is_active:
                    raise ValidationError("Your account has been deactivated. Contact support.")
                if not user.is_approved:
                    raise ValidationError("Your account is pending approval. Please wait for admin confirmation.")
            except User.DoesNotExist:
                pass  # Let parent form handle invalid username/password
        
        return cleaned_data


class CustomUserCreationForm(UserCreationForm):
    """Registration form for admin/official users."""
    username = forms.CharField(
        label="Username",
        max_length=150,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Choose a username',
        }),
        help_text="Letters, digits and @/./+/-/_ only.",
    )
    email = forms.EmailField(
        label="Email Address",
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter your email',
        }),
    )
    password1 = forms.CharField(
        label="Password",
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter a strong password',
        }),
    )
    password2 = forms.CharField(
        label="Confirm Password",
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Confirm your password',
        }),
    )
    role = forms.ChoiceField(
        label="Role",
        choices=[('admin', 'Administrator'), ('official', 'Official')],
        widget=forms.Select(attrs={
            'class': 'form-control',
        }),
    )
    organization = forms.CharField(
        label="Organization/Barangay",
        max_length=255,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'e.g., Barangay Pembo',
        }),
    )

    class Meta:
        model = User
        fields = ('username', 'email', 'password1', 'password2', 'role', 'organization')

    def clean_username(self):
        username = self.cleaned_data.get('username')
        if User.objects.filter(username=username).exists():
            raise ValidationError("This username is already taken.")
        return username

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if User.objects.filter(email=email).exists():
            raise ValidationError("This email is already registered.")
        return email

    def clean_password2(self):
        password1 = self.cleaned_data.get('password1')
        password2 = self.cleaned_data.get('password2')
        if password1 and password2 and password1 != password2:
            raise ValidationError("Passwords do not match.")
        return password2


class PasswordResetRequestForm(forms.Form):
    """Form to request password reset via email."""
    email = forms.EmailField(
        label="Email Address",
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter your registered email',
        }),
    )

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if not User.objects.filter(email=email).exists():
            raise ValidationError("No account found with this email address.")
        return email


class SensorNodeForm(forms.ModelForm):
    """Form for creating/editing sensor nodes."""
    class Meta:
        model = SensorNode
        fields = ['name', 'mac_address', 'location', 'latitude', 'longitude', 'organization', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., Node-Pembo-01',
            }),
            'mac_address': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., AA:BB:CC:DD:EE:FF',
            }),
            'location': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., Villamor Air Base, Taguig',
            }),
            'latitude': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': '14.5631',
                'step': '0.0001',
            }),
            'longitude': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': '121.0192',
                'step': '0.0001',
            }),
            'organization': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., EMBO',
            }),
            'is_active': forms.CheckboxInput(attrs={
                'class': 'form-check-input',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # If editing an existing instance, make MAC address readonly
        if self.instance.pk:
            self.fields['mac_address'].widget.attrs['readonly'] = True
            self.fields['mac_address'].disabled = True

    def clean_latitude(self):
        latitude = self.cleaned_data.get('latitude')
        if latitude is not None and (latitude < -90 or latitude > 90):
            raise ValidationError("Latitude must be between -90 and 90.")
        return latitude

    def clean_longitude(self):
        longitude = self.cleaned_data.get('longitude')
        if longitude is not None and (longitude < -180 or longitude > 180):
            raise ValidationError("Longitude must be between -180 and 180.")
        return longitude

class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ['name', 'description', 'price', 'stock', 'image', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'e.g. U-Node V1'}),
            'description': forms.Textarea(attrs={'class': 'form-input', 'rows': 3}),
            'price': forms.NumberInput(attrs={'class': 'form-input'}),
            'stock': forms.NumberInput(attrs={'class': 'form-input'}),
        }