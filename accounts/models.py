from django.db import models
from django.contrib.auth.models import AbstractUser

class User(AbstractUser):
    ROLE_CHOICES = [
        ('admin', 'Admin'),
        ('management', 'Management'),
        ('supervisor', 'Supervisor'),
        ('engineer', 'Engineer'),
        ('maintenance', 'Maintenance'),
        ('leadman', 'Leadman'),
        ('operator', 'Operator'),
    ]
    
    POSITION_CHOICES = [
        ('THREAD', 'THREAD'),
        ('WELD', 'WELD'),
    ]
    
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='operator')
    
    operator = models.OneToOneField(
        'production.Operator',
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='user_account'
    )
    
    # Field baru untuk employee_id manual
    manual_employee_id = models.CharField(
        max_length=20, 
        null=True, 
        blank=True,
        verbose_name='Employee ID',
        help_text='Employee ID for non-operator roles'
    )
    
    position = models.CharField(
        max_length=50, 
        choices=POSITION_CHOICES,
        null=True, 
        blank=True,
        verbose_name='Position',
        help_text='Position for Leadman role (THREAD or WELD)'
    )
    
    signature = models.ImageField(upload_to='signatures/', null=True, blank=True)
    phone_number = models.CharField(max_length=20, null=True, blank=True)
    department = models.CharField(max_length=50, null=True, blank=True)
    is_active_operator = models.BooleanField(default=True)
    
    @property
    def employee_id(self):
        """
        Returns employee_id from Operator model for operators,
        or manual_employee_id for other roles
        """
        if self.operator:
            return self.operator.employee_id
        return self.manual_employee_id
    
    @property
    def full_name(self):
        if self.operator:
            return self.operator.name
        return f"{self.first_name} {self.last_name}".strip() or self.username
    
    @property
    def initial_name(self):
        if self.operator and self.operator.initial:
            return self.operator.initial
        return self.username[:3].upper()
    
    @property
    def work_station(self):
        if self.operator:
            return self.operator.work_station
        return None
    
    @property
    def user_position(self):
        if self.operator:
            return self.operator.position
        return self.position

    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"
    
    class Meta:
        verbose_name = 'User'
        verbose_name_plural = 'Users'