from django.urls import path
from . import views
from django.conf import settings             # <-- Add this
from django.conf.urls.static import static   # <-- Add this
from django.contrib import admin
from django.urls import include

app_name = 'app'

urlpatterns = [
    # PUBLIC PAGES
    path('', views.dashboard, name='dashboard'),
    path('realtime/', views.realtime, name='realtime'),
    path('map/', views.map_view, name='map'),
    path('history/', views.history, name='history'),
    path('alerts/', views.alerts, name='alerts'),
    path('health/', views.health, name='health'),
    path('about/', views.about, name='about'),
    path('shop/', views.shop_view, name='shop'),
    path('shop/checkout/<int:product_id>/', views.dummy_checkout, name='checkout'),
    
    # AUTH ROUTES
    path('login/', views.login_view, name='login'),
    path('signup/', views.signup_view, name='signup'),
    path('logout/', views.logout_view, name='logout'),
    path('forgot-password/', views.forgot_password_request, name='forgot_password'),
    path('reset-password/<uidb64>/<token>/', views.reset_password, name='reset_password'),
    path('change-password/', views.change_password, name='change_password'),
    path('force-password-change/', views.force_password_change, name='force_password_change'),
    path('activate/<uidb64>/<token>/', views.activate_user, name='activate_user'),
    path('dashboard/hardware-inventory/', views.hardware_inventory_view, name='hardware_inventory'),
    
    # PASSWORD RESET ADMIN MODERATION
    path('admin/password-reset-requests/', views.admin_password_reset_requests, name='admin_password_reset_requests'),
    path('admin/password-reset/<int:alert_id>/approve/', views.admin_approve_password_reset, name='admin_approve_password_reset'),
    path('admin/password-reset/<int:alert_id>/deny/', views.admin_deny_password_reset, name='admin_deny_password_reset'),
    
    # ADMIN PAGES
    path('dashboard/dashboard/', views.client_dashboard, name='client_dashboard'),
    path('dashboard/analytics/', views.client_analytics, name='client_analytics'),
    path('dashboard/history/', views.client_history, name='client_history'),
    path('dashboard/alerts/', views.client_alerts, name='client_alerts'),
    path('dashboard/devices/', views.client_devices, name='client_devices'),
    path('dashboard/health/', views.client_health, name='client_health'),
    path('dashboard/map/', views.client_map_view, name='client_map'),
    path('dashboard/map/node/create/', views.node_create, name='node_create'),
    path('dashboard/map/node/<int:pk>/edit/', views.node_edit, name='node_edit'),
    path('dashboard/map/node/<int:pk>/delete/', views.node_delete, name='node_delete'),
    path('dashboard/realtime/', views.client_realtime, name='client_realtime'),
    path('api/client-reports/', views.api_client_reports, name='api_client_reports'),
    path('dashboard/settings/', views.client_settings, name='client_settings'),
    path('dashboard/users/', views.client_users, name='client_users'),
    path('dashboard/ai/', views.client_ai, name='client_ai'),
    path('dashboard/hardware-inventory/<int:product_id>/delete/', views.hardware_delete_view, name='hardware_delete'),
    
    # API ENDPOINTS for ESP8266 Sensor Integration
    path('api/sensor-data/', views.api_sensor_data, name='api_sensor_data'),
    path('api/sensor/latest/', views.api_sensor_latest, name='api_sensor_latest'),
    path('api/sensor/node/<int:node_id>/history/', views.api_sensor_node_history, name='api_sensor_history'),
    
    # API ENDPOINTS for Analytics (future-proof for async updates)
    path('api/analytics/', views.api_analytics, name='api_analytics'),
    path('api/analytics/top-areas/', views.api_analytics_top_areas, name='api_analytics_top_areas'),
    path('api/dashboard/nodes/', views.api_dashboard_nodes, name='api_dashboard_nodes'),
    path('api/realtime-data/', views.api_realtime_data, name='api_realtime_data'),
    
    # API ENDPOINTS for Dynamic Analytics Dashboard
    path('api/analytics/overview/', views.api_analytics_overview, name='api_analytics_overview'),
    path('api/analytics/trends/', views.api_analytics_trends, name='api_analytics_trends'),
    path('api/analytics/top-areas/', views.api_analytics_top_areas, name='api_analytics_top_areas'),
    path('api/analytics/aqi-trend/', views.api_analytics_aqi_trend, name='api_analytics_aqi_trend'),
    path('api/analytics/system-health/', views.api_analytics_system_health, name='api_analytics_system_health'),
    
    # SPIKE MANAGEMENT API ENDPOINTS
    path('api/spike/delete/', views.api_spike_delete, name='api_spike_delete'),
    path('api/spike/flag/', views.api_spike_flag, name='api_spike_flag'),
    
    # OPTIMIZATION: New map view API endpoints (viewport rendering, limited data)
    path('api/daily-forecast/', views.api_daily_forecast, name='api_daily_forecast'),
    path('api/nodes/viewport/', views.api_nodes_viewport, name='api_nodes_viewport'),
    path('api/nodes/live/', views.api_nodes_live, name='api_nodes_live'),
    path('api/nodes/24h/', views.api_nodes_24h, name='api_nodes_24h'),
    path('api/nodes/', views.api_nodes_list, name='api_nodes_list'),
    path('api/nodes/<int:node_id>/detail/', views.api_node_detail, name='api_node_detail'),
    path('api/nodes/<int:node_id>/readings/', views.api_node_readings, name='api_node_readings'),
    path('api/nodes/<int:node_id>/readings/export/', views.api_node_readings_export, name='api_node_readings_export'),
    path('api/readings/<int:reading_id>/delete/', views.api_node_reading_delete, name='api_node_reading_delete'),

    # API ENDPOINTS for User Management
    path('api/auth/me/', views.api_auth_me, name='api_auth_me'),
    path('api/users/', views.api_users, name='api_users'),
    path('api/users/create/', views.api_users_create, name='api_users_create'),
    path('api/users/invite/', views.api_users_invite, name='api_users_invite'),
    path('api/users/<int:user_id>/update/', views.api_users_update, name='api_users_update'),
    path('api/users/<int:user_id>/toggle/', views.api_users_toggle, name='api_users_toggle'),
    path('api/users/<int:user_id>/delete/', views.api_users_delete, name='api_users_delete'),
    path('api/users/<int:user_id>/resend-invite/', views.api_users_resend_invite, name='api_users_resend_invite'),
    path('api/users/<int:user_id>/invite-link/', views.api_users_invite_link, name='api_users_invite_link'),
    path('api/users/<int:user_id>/reset-password/', views.api_users_reset_password, name='api_users_reset_password'),

    path('export/pdf/', views.export_report_pdf, name='export_report_pdf'),
    path('export/csv/', views.export_report_csv, name='export_report_csv'),
    path('export/excel/', views.export_report_excel, name='export_report_excel'),
    path('export/print/', views.export_report_print, name='export_report_print'),

    path('api/analytics/', views.api_analytics, name='api_analytics'),
    path('api/chat/', views.api_enviro_ai_chat, name='api_enviro_ai_chat'),
    path('api/ai-insights/', views.api_ai_insights, name='api_ai_insights'),

    path('api/notifications/unread/', views.api_notifications_unread, name='api_notifications_unread'),
    path('api/notifications/list/', views.api_notifications_list, name='api_notifications_list'),
    path('api/notifications/<int:notification_id>/read/', views.api_notification_mark_read, name='api_notification_mark_read'),
    path('api/notifications/mark-all-read/', views.api_notifications_mark_all_read, name='api_notifications_mark_all_read'),


    path('api/closest-node/', views.api_closest_node, name='api_closest_node'),

]
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)