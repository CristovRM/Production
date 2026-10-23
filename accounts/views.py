from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.views import LoginView, LogoutView
from django.contrib.auth import get_user_model, login
from django.urls import reverse_lazy
from django.db.models import Q
from django.contrib import messages
from django.core.paginator import Paginator
from django.contrib.auth.hashers import make_password
from django.contrib.auth.decorators import login_required
from django.templatetags.static import static
from django.core.exceptions import PermissionDenied
from production.models import Operator
from functools import wraps

User = get_user_model()

# Decorator custom untuk check role admin
def admin_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')
        if request.user.role != 'admin':
            messages.error(request, "You don't have permission to access this page. Admin access only.")
            return redirect('dashboard')
        return view_func(request, *args, **kwargs)
    return wrapper

class CustomLoginView(LoginView):
    template_name = 'login.html'
    success_url = reverse_lazy('dashboard')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['logo_url'] = self.request.build_absolute_uri(static('assets/images/nov-logo.png'))
        return context
    
    def form_valid(self, form):
        username_or_email = form.cleaned_data.get('username')
        password = form.cleaned_data.get('password')
        
        try:
            user = User.objects.get(
                Q(username__iexact=username_or_email) | 
                Q(email__iexact=username_or_email)
            )
            
            if user.check_password(password) and user.is_active:
                login(self.request, user)
                
                # Set session data
                self.request.session['user_id'] = user.id
                self.request.session['username'] = user.username
                self.request.session['role'] = user.role
                
                # Add operator-specific session data if applicable
                if user.role == 'operator' and user.operator:
                    self.request.session['operator_id'] = user.operator.id
                    self.request.session['operator_position'] = user.operator.position
                    self.request.session['operator_name'] = user.operator.name
                
                # Session permanen untuk semua user (1 tahun)
                # User hanya logout saat klik tombol Logout
                self.request.session.set_expiry(31536000)  # 1 tahun (365 hari)
                
                messages.success(self.request, f'Welcome back, {user.username}!')
                return redirect(self.get_success_url())
            else:
                messages.error(self.request, 'Invalid email/username or password.')
                return self.form_invalid(form)
                
        except User.DoesNotExist:
            messages.error(self.request, 'Invalid email/username or password.')
            return self.form_invalid(form)

    def get_success_url(self):
        user = self.request.user
        
        # Check if user is operator role
        if user.role == 'operator' and user.operator:
            position = user.operator.position
            
            # Redirect based on operator position
            if position == 'THREAD':
                return reverse_lazy('thread_list')
            elif position == 'WELD':
                return reverse_lazy('weld_list')
            else:
                # Jika position tidak dikenali, redirect ke dashboard
                return reverse_lazy('dashboard')
        
        # For non-operator roles, redirect to default success_url or dashboard
        return self.success_url or reverse_lazy('dashboard')

class CustomLogoutView(LogoutView):
    next_page = 'login'
    
    def dispatch(self, request, *args, **kwargs):
        # Clear session data before logout
        if request.user.is_authenticated:
            # Optional: log the logout action
            username = request.session.get('username', request.user.username)
            
            # Clear all session data
            request.session.flush()
            
            messages.info(request, f'You have been logged out successfully.')
        
        return super().dispatch(request, *args, **kwargs)

@login_required
def landing_page(request):
    logo_url = request.build_absolute_uri(static('assets/images/nov-logo.png'))
    
    context = {
        'logo_url': logo_url,
    }
    return render(request, 'landing_page.html', context)

# ============================================
# USER MANAGEMENT - ADMIN ONLY
# ============================================

@admin_required
def user_list(request):
    """
    View daftar user - Hanya Admin yang bisa akses
    """
    query = request.GET.get('q', '')

    items = User.objects.select_related('operator').all().order_by('-date_joined')

    if query:
        items = items.filter(
            Q(username__icontains=query) |
            Q(first_name__icontains=query) |
            Q(last_name__icontains=query) |
            Q(email__icontains=query) |
            Q(role__icontains=query) |
            Q(operator__employee_id__icontains=query) |
            Q(operator__name__icontains=query)
        )

    paginator = Paginator(items, 50)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'items': page_obj,
        'query': query,
        'active_menu': 'user_list',
    }
    return render(request, 'users/list.html', context)

@admin_required
def user_add(request):
    """
    View tambah user - Hanya Admin yang bisa akses
    """
    if request.method == 'POST':
        username = request.POST.get('username')
        email = request.POST.get('email')
        first_name = request.POST.get('first_name')
        last_name = request.POST.get('last_name')
        role = request.POST.get('role')
        password = request.POST.get('password')
        confirm_password = request.POST.get('confirm_password')
        is_active = request.POST.get('is_active') == 'on'
        
        # Field tambahan
        operator_id = request.POST.get('operator')
        manual_employee_id = request.POST.get('manual_employee_id')
        position = request.POST.get('position')  # NEW: Field position untuk Leadman
        phone_number = request.POST.get('phone_number')
        department = request.POST.get('department')
        is_active_operator = request.POST.get('is_active_operator') == 'on'
        signature = request.FILES.get('signature')

        # Validasi wajib
        if not username or not password or not role:
            messages.error(request, "Username, Password, dan Role wajib diisi.")
            return redirect('user_add')

        # Validasi password confirmation
        if password != confirm_password:
            messages.error(request, "Password dan konfirmasi password tidak cocok.")
            return redirect('user_add')

        # Cek username sudah ada atau belum
        if User.objects.filter(username=username).exists():
            messages.error(request, "Username sudah digunakan.")
            return redirect('user_add')

        # Cek email sudah ada atau belum (jika diisi)
        if email and User.objects.filter(email=email).exists():
            messages.error(request, "Email sudah digunakan.")
            return redirect('user_add')

        # Validasi operator jika role adalah operator
        if role == 'operator' and not operator_id:
            messages.error(request, "User dengan role Operator harus dihubungkan dengan data Operator.")
            return redirect('user_add')
        
        # NEW: Validasi position jika role adalah leadman
        if role == 'leadman' and not position:
            messages.error(request, "User dengan role Leadman harus memilih Position (THREAD atau WELD).")
            return redirect('user_add')

        # Cek apakah operator sudah digunakan user lain
        if operator_id:
            if User.objects.filter(operator_id=operator_id).exists():
                messages.error(request, "Operator ini sudah terhubung dengan user lain.")
                return redirect('user_add')

        # Buat user
        user = User.objects.create(
            username=username,
            email=email,
            first_name=first_name,
            last_name=last_name,
            role=role,
            password=make_password(password),
            is_active=is_active,
            operator_id=operator_id if operator_id else None,
            manual_employee_id=manual_employee_id if manual_employee_id else None,
            position=position if position else None,
            phone_number=phone_number,
            department=department,
            is_active_operator=is_active_operator
        )
        if signature:
            user.signature = signature
            user.save()

        messages.success(request, "Pengguna berhasil ditambahkan.")
        return redirect('user_list')
    operators = Operator.objects.filter(user_account__isnull=True).order_by('name')

    return render(request, 'users/add.html', {
        'role_choices': User.ROLE_CHOICES,
        'position_choices': User.POSITION_CHOICES,
        'operators': operators,
        'active_menu': 'user_list'
    })

@admin_required
def user_edit(request, pk):
    """
    View edit user - Hanya Admin yang bisa akses
    """
    item = get_object_or_404(User, pk=pk)

    if request.method == 'POST':
        item.username = request.POST.get('username')
        item.email = request.POST.get('email')
        item.first_name = request.POST.get('first_name')
        item.last_name = request.POST.get('last_name')
        item.role = request.POST.get('role')
        password = request.POST.get('password')
        confirm_password = request.POST.get('confirm_password')
        item.is_active = request.POST.get('is_active') == 'on'
        
        # Field tambahan
        operator_id = request.POST.get('operator')
        item.manual_employee_id = request.POST.get('manual_employee_id')
        item.position = request.POST.get('position')  # NEW: Field position
        item.phone_number = request.POST.get('phone_number')
        item.department = request.POST.get('department')
        item.is_active_operator = request.POST.get('is_active_operator') == 'on'
        signature = request.FILES.get('signature')
        remove_signature = request.POST.get('remove_signature') == 'on'

        # Validasi wajib diisi
        if not item.username or not item.role:
            messages.error(request, "Username dan Role wajib diisi.")
            return redirect('user_edit', pk=pk)

        # Cek username duplikat (kecuali user saat ini)
        if User.objects.filter(username=item.username).exclude(pk=pk).exists():
            messages.error(request, "Username sudah digunakan.")
            return redirect('user_edit', pk=pk)

        # Cek email duplikat (kecuali user saat ini dan jika diisi)
        if item.email and User.objects.filter(email=item.email).exclude(pk=pk).exists():
            messages.error(request, "Email sudah digunakan.")
            return redirect('user_edit', pk=pk)

        # Validasi operator jika role adalah operator
        if item.role == 'operator' and not operator_id:
            messages.error(request, "User dengan role Operator harus dihubungkan dengan data Operator.")
            return redirect('user_edit', pk=pk)
        
        # NEW: Validasi position jika role adalah leadman
        if item.role == 'leadman' and not item.position:
            messages.error(request, "User dengan role Leadman harus memilih Position (THREAD atau WELD).")
            return redirect('user_edit', pk=pk)

        # Cek apakah operator sudah digunakan user lain
        if operator_id:
            if User.objects.filter(operator_id=operator_id).exclude(pk=pk).exists():
                messages.error(request, "Operator ini sudah terhubung dengan user lain.")
                return redirect('user_edit', pk=pk)

        # Update operator
        item.operator_id = operator_id if operator_id else None

        # Update password jika diisi
        if password:
            if password != confirm_password:
                messages.error(request, "Password dan konfirmasi password tidak cocok.")
                return redirect('user_edit', pk=pk)
            item.password = make_password(password)

        # Handle signature
        if remove_signature and item.signature:
            item.signature.delete()
            item.signature = None
        elif signature:
            if item.signature:
                item.signature.delete()
            item.signature = signature

        item.save()

        messages.success(request, "Pengguna berhasil diperbarui.")
        return redirect('user_list')
    operators = Operator.objects.filter(
        Q(user_account__isnull=True) | Q(user_account=item)
    ).order_by('name')

    return render(request, 'users/edit.html', {
        'item': item,
        'role_choices': User.ROLE_CHOICES,
        'position_choices': User.POSITION_CHOICES,
        'operators': operators,
        'active_menu': 'user_list'
    })

@admin_required
def index(request):
    """
    Index page - Dashboard untuk Admin menampilkan statistik user berdasarkan role
    """
    # Hitung total user per role
    stats = {
        'total_users': User.objects.filter(is_active=True).count(),
        'admin_count': User.objects.filter(role='admin', is_active=True).count(),
        'management_count': User.objects.filter(role='management', is_active=True).count(),
        'supervisor_count': User.objects.filter(role='supervisor', is_active=True).count(),
        'engineer_count': User.objects.filter(role='engineer', is_active=True).count(),
        'maintenance_count': User.objects.filter(role='maintenance', is_active=True).count(),
        'leadman_count': User.objects.filter(role='leadman', is_active=True).count(),
        'operator_count': User.objects.filter(role='operator', is_active=True).count(),
    }
    
    # User terbaru (5 terakhir)
    recent_users = User.objects.filter(is_active=True).order_by('-date_joined')[:5]
    
    context = {
        'stats': stats,
        'recent_users': recent_users,
    }
    
    return render(request, 'accounts/index.html', context)