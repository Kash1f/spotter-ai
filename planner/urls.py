from django.urls import path
from django.views.generic import TemplateView

from . import views

urlpatterns = [
    path('fuel-planner/', TemplateView.as_view(template_name='planner/fuel_planner.html'), name='fuel-planner'),
    path('api/v1/route/', views.RouteView.as_view(), name='route'),
]
