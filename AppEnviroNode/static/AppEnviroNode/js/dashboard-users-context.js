{% extends 'AppEnviroNode/index.html' %}
{% load static %}

{% block title %}Admin - Dashboard - Environode{% endblock %}

{% block extra_head %}
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet.markercluster/1.5.1/MarkerCluster.min.css"/>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet.markercluster/1.5.1/MarkerCluster.Default.min.css"/>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
  <script src="https://unpkg.com/@phosphor-icons/web"></script>
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet.markercluster/1.5.1/leaflet.markercluster.min.js"></script>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.0/css/all.min.css">
{% endblock %}

{% block content %}
    <style>
        /* GLOBAL VARIABLES & LIGHT THEME */
        :root {
            --cd-bg: #f6f8fb;
            --cd-card-bg: #ffffff;
            --cd-card-hover: #f9fafb;
            --cd-border: #e5e7eb;
            --cd-text-main: #1f2937;
            --cd-text-muted: #6b7280;
            
            /* Semantic Identity Colors */
            --cd-green: #10b981;       
            --cd-green-bg: rgba(16, 185, 129, 0.15);
            --cd-yellow: #f59e0b;      
            --cd-yellow-text: #b45309; 
            --cd-yellow-bg: rgba(245, 158, 11, 0.15);
            --cd-red: #ef4444;         
            --cd-red-bg: rgba(239, 68, 68, 0.1);
            --cd-blue: #3b82f6;        
            --cd-blue-bg: rgba(59, 130, 246, 0.15);
            --cd-purple: #8b5cf6;      
            --cd-purple-bg: rgba(139, 92, 246, 0.15);
            --cd-cyan: #0891b2;        
            --cd-cyan-bg: rgba(6, 182, 212, 0.15);
            --cd-orange: #ea580c;      
            --cd-slate: #64748b;
            /* AQI Colors for markers */
            --aqi-good: #10b981;
            --aqi-moderate: #f59e0b;
            --aqi-sensitive: #f97316;
            --aqi-unhealthy: #ef4444;
            --aqi-very-unhealthy: #8b5cf6;
            --aqi-hazardous: #7f1d1d;
            --aqi-offline: #94a3b8;
        }

        * { box-sizing: border-box; margin: 0; padding: 0; }

        /* GRID LAYOUT */
        .cdashboard-wrapper {
            display: grid;
            grid-template-columns: repeat(12, 1fr);
            gap: 10px;
            max-width: 100%;
            margin: 0 auto;
        }

        /* 1. PRIMARY INCIDENT CARD */
        .cd-incident-primary {
            grid-column: span 12;
            background: #fffcfc;
            border: 1px solid var(--cd-red);
            border-left: 5px solid var(--cd-red);
            border-radius: 8px;
            padding: 12px 16px;
            display: flex;
            align-items: flex-start;
            justify-content: space-between;
            gap: 16px;
            animation: pulse-critical-glow 3s infinite alternate;
        }

        .cd-incident-primary.clear {
            background: #f0fdf4;
            border-color: var(--cd-green);
            border-left-color: var(--cd-green);
            animation: none;
        }

        @keyframes pulse-critical-glow {
            0% { box-shadow: 0 4px 12px rgba(239, 68, 68, 0.08); }
            100% { box-shadow: 0 4px 20px rgba(239, 68, 68, 0.25); }
        }

        .cd-incident-col { display: flex; flex-direction: column; gap: 4px; }
        .cd-incident-title { font-size: 14px; font-weight: 800; color: var(--cd-red); display: flex; align-items: center; gap: 6px; text-transform: uppercase; letter-spacing: 0.02em; }
        .cd-incident-title.clear { color: var(--cd-green); }
        .cd-incident-detail { font-size: 13px; font-weight: 600; color: var(--cd-text-main); }
        .cd-incident-impact { display: flex; gap: 12px; font-size: 12px; font-weight: 500; color: var(--cd-text-muted); }
        .cd-incident-impact span { color: var(--cd-text-main); font-weight: 700; }
        
        .cd-time-context-block {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 4px 12px;
            background: var(--cd-red-bg);
            padding: 6px 10px;
            border-radius: 6px;
            border: 1px solid rgba(239, 68, 68, 0.2);
            font-size: 10px;
            font-weight: 600;
            color: #7f1d1d;
        }
        .cd-time-context-block.clear {
            background: var(--cd-green-bg);
            border-color: rgba(16, 185, 129, 0.2);
            color: #064e3b;
        }
        .cd-time-context-block span { font-weight: 800; color: var(--cd-red); display: flex; align-items: center; gap: 4px;}
        .cd-time-context-block.clear span { color: var(--cd-green); }

        .cd-time-tag { padding: 2px 6px; border-radius: 4px; font-size: 9px; font-weight: 800; text-transform: uppercase; letter-spacing: 0.05em; display: inline-flex; align-items: center; }
        .cd-time-tag.new { background: var(--cd-red); color: white; }
        .cd-time-tag.ongoing { background: var(--cd-yellow); color: white; }
        .cd-time-tag.stable { background: var(--cd-green); color: white; }

        .cd-secondary-issues {
            grid-column: span 12;
            display: flex;
            gap: 8px;
            margin-bottom: 2px;
            flex-wrap: wrap;
        }
        .cd-secondary-pill {
            padding: 6px 12px;
            border-radius: 6px;
            font-size: 11px;
            font-weight: 700;
            display: flex;
            align-items: center;
            gap: 6px;
            background: var(--cd-card-bg);
            border: 1px solid var(--cd-border);
            box-shadow: 0 1px 2px rgba(0,0,0,0.02);
            cursor: pointer;
            transition: 0.2s;
        }
        .cd-secondary-pill:hover { transform: translateY(-1px); box-shadow: 0 3px 6px rgba(0,0,0,0.05); }
        .cd-secondary-pill.yellow { border-left: 3px solid var(--cd-yellow); color: var(--cd-text-main); }
        .cd-secondary-pill.orange { border-left: 3px solid var(--cd-orange); color: var(--cd-text-main); }
        .cd-secondary-pill.green { border-left: 3px solid var(--cd-green); color: var(--cd-green); }
        .cd-secondary-pill i { font-size: 14px; }

        .cdashboard-card {
            background: var(--cd-card-bg);
            border: 1px solid var(--cd-border);
            border-radius: 8px;
            display: flex;
            flex-direction: column;
            overflow: hidden;
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
            transition: border-color 0.2s;
        }

        .cdashboard-card-header {
            padding: 8px 12px;
            font-size: 11px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: var(--cd-text-muted);
            display: flex;
            align-items: center;
            justify-content: space-between;
            border-bottom: 1px solid var(--cd-border);
            background: var(--cd-card-bg);
        }
        .cd-header-left { display: flex; align-items: center; gap: 6px; }

        .cdashboard-card-body {
            padding: 10px 12px;
            flex: 1;
            display: flex;
            flex-direction: column;
            justify-content: center;
            gap: 8px;
        }

        .cd-confidence-bar {
            display: flex;
            align-items: center;
            justify-content: space-between;
            background: var(--cd-bg);
            padding: 6px 8px;
            border-radius: 6px;
            border: 1px dashed var(--cd-border);
            margin-bottom: 4px;
        }
        .cd-confidence-text { font-size: 10px; font-weight: 600; color: var(--cd-text-muted); display: flex; align-items: center; gap: 4px;}
        .cd-confidence-val { font-size: 11px; font-weight: 800; }
        .cd-confidence-val.degraded { color: var(--cd-yellow-text); }
        .cd-confidence-val.high { color: var(--cd-green); }

        .shimmer-text {
            background: linear-gradient(90deg, var(--cd-text-main) 0%, #cbd5e1 50%, var(--cd-text-main) 100%);
            background-size: 200% auto;
            color: transparent;
            -webkit-background-clip: text;
            background-clip: text;
            animation: shimmer 2s linear infinite;
        }
        @keyframes shimmer { to { background-position: 200% center; } }
        
        .spin { animation: spin 1s linear infinite; }
        @keyframes spin { 100% { transform: rotate(360deg); } }

        [data-tooltip] { position: relative; cursor: help; border-bottom: 1px dotted currentColor; }
        [data-tooltip]::after {
            content: attr(data-tooltip);
            position: absolute; bottom: 100%; left: 50%; transform: translateX(-50%) translateY(4px);
            background: #1f2937; color: #fff; padding: 6px 10px; border-radius: 6px; font-size: 10px; font-weight: 600;
            white-space: nowrap; opacity: 0; pointer-events: none; transition: 0.2s; z-index: 10; margin-bottom: 6px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1); border: 1px solid #374151; letter-spacing: normal; text-transform: none;
        }
        [data-tooltip]:hover::after { opacity: 1; transform: translateX(-50%) translateY(0); }

        .cdashboard-quick-access {
            display: flex;
            align-items: center;
            justify-content: flex-end;
            padding: 6px 12px;
            font-size: 10px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: var(--cd-slate);
            background: transparent;
            text-decoration: none;
            transition: all 0.2s;
            margin-top: -4px;
        }
        .cdashboard-quick-access:hover { color: var(--cd-text-main); }
        .cdashboard-quick-access.urgent { color: var(--cd-red); }
        .cdashboard-quick-access.urgent:hover { color: #b91c1c; }

        .cd-link-hint {
            font-size: 10px;
            font-weight: 600;
            color: var(--cd-slate);
            display: flex;
            align-items: flex-start;
            gap: 4px;
            margin-top: auto;
            padding-top: 6px;
            border-top: 1px dashed var(--cd-border);
        }
        .cd-link-hint i { font-size: 12px; color: var(--cd-orange); margin-top: 1px; }

        .cd-metric-row { display: flex; justify-content: space-between; align-items: center; }
        .cd-metric-label { color: var(--cd-text-muted); font-size: 11px; font-weight: 500; }
        .cd-metric-val { font-weight: 700; display: flex; align-items: center; gap: 6px; font-size: 12px; }
        
        .cd-trend { font-size: 10px; font-weight: 700; display: flex; align-items: center; gap: 2px; }
        .cd-trend.critical { color: var(--cd-red); background: var(--cd-red-bg); padding: 2px 4px; border-radius: 4px;}
        .cd-trend.moderate { color: var(--cd-yellow-text); }
        .cd-trend.slow { color: var(--cd-slate); }
        .cd-trend.good { color: var(--cd-green); }

        .cd-pill { padding: 2px 6px; border-radius: 4px; font-size: 9px; font-weight: 700; text-transform: uppercase; }
        .cd-pill.green { background: var(--cd-green-bg); color: var(--cd-green); }
        .cd-pill.blue { background: var(--cd-blue-bg); color: var(--cd-blue); }
        .cd-pill.red { background: var(--cd-red-bg); color: var(--cd-red); }
        .cd-pill.purple { background: var(--cd-purple-bg); color: var(--cd-purple); }

        /* CARD IDENTITIES & SIZING */
        .cdashboard-environment { grid-column: span 4; border-top: 3px solid var(--cd-yellow); }
        .cdashboard-system-health { grid-column: span 4; border-top: 3px solid var(--cd-green); }
        .cdashboard-devices { grid-column: span 4; border-top: 3px solid var(--cd-purple); }
        
        /* SPATIAL CONTEXT CARD - MATCH MAP VIEW STYLES */
        .cdashboard-map { 
            grid-column: span 6; 
            border-top: 3px solid var(--cd-slate);
            min-height: 500px;
        }
        .cdashboard-network { grid-column: span 3; border-top: 3px solid var(--cd-blue); }
        .cdashboard-pipeline { grid-column: span 3; border-top: 3px solid var(--cd-orange); }
        .cdashboard-admin { grid-column: span 3; border-top: 3px solid var(--cd-slate); }

        /* MAP CONTAINER - MATCH MAP VIEW */
        .cd-real-map-container {
            position: relative;
            height: 350px;
            border-radius: 6px;
            overflow: hidden;
            border: 1px solid var(--cd-border);
            background: #f1f5f9;
        }
        .cd-real-map {
            width: 100%;
            height: 100%;
        }
        .cd-real-map .leaflet-container {
            width: 100%;
            height: 100%;
            background: #f8fafc;
        }

        /* Map Controls - MATCH MAP VIEW */
        .cd-map-controls {
            position: absolute;
            top: 10px;
            left: 10px;
            background: rgba(255, 255, 255, 0.95);
            backdrop-filter: blur(8px);
            border: 1px solid var(--cd-border);
            border-radius: 6px;
            padding: 8px 10px;
            box-shadow: 0 2px 6px rgba(0,0,0,0.1);
            width: 200px;
            z-index: 10;
        }
        .cd-control-group { margin-bottom: 8px; }
        .cd-control-group:last-child { margin-bottom: 0; }
        .cd-control-label {
            font-size: 0.65rem;
            font-weight: 700;
            color: var(--cd-text-muted);
            text-transform: uppercase;
            margin-bottom: 4px;
            display: block;
        }
        .cd-select-input {
            width: 100%;
            padding: 4px 6px;
            border-radius: 4px;
            border: 1px solid var(--cd-border);
            background: var(--cd-card-bg);
            font-size: 0.75rem;
        }
        .cd-toggle-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 4px;
            font-size: 0.75rem;
            font-weight: 600;
        }
        .cd-toggle-switch {
            width: 26px;
            height: 14px;
            background: var(--cd-green);
            border-radius: 12px;
            position: relative;
            cursor: pointer;
        }
        .cd-toggle-switch::after {
            content: '';
            position: absolute;
            top: 2px;
            left: 14px;
            width: 10px;
            height: 10px;
            background: white;
            border-radius: 50%;
            transition: 0.2s;
        }
        .cd-toggle-switch.cd-off {
            background: #d1d5db;
        }
        .cd-toggle-switch.cd-off::after {
            left: 2px;
        }
        .cd-btn-group {
            display: flex;
            border-radius: 4px;
            overflow: hidden;
            border: 1px solid var(--cd-border);
        }
        .cd-btn-group button {
            flex: 1;
            padding: 4px 0;
            background: var(--cd-card-bg);
            border: none;
            border-right: 1px solid var(--cd-border);
            font-size: 0.7rem;
            font-weight: 600;
            cursor: pointer;
            color: var(--cd-text-muted);
        }
        .cd-btn-group button:last-child { border-right: none; }
        .cd-btn-group button.cd-active {
            background: #f3f4f6;
            color: var(--cd-text-main);
        }

        /* Map Legend */
        .cd-map-legend {
            position: absolute;
            bottom: 10px;
            right: 10px;
            background: rgba(255, 255, 255, 0.95);
            border-radius: 6px;
            padding: 6px 10px;
            box-shadow: 0 2px 6px rgba(0,0,0,0.1);
            border: 1px solid var(--cd-border);
            font-size: 0.7rem;
            z-index: 10;
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
        }
        .cd-legend-title {
            font-weight: 800;
            padding-right: 6px;
            border-right: 1px solid var(--cd-border);
        }
        .cd-legend-item {
            display: flex;
            align-items: center;
            gap: 4px;
        }
        .cd-legend-color {
            width: 10px;
            height: 10px;
            border-radius: 50%;
        }

        .cd-map-stats {
            display: flex;
            justify-content: space-between;
            margin-top: 8px;
            padding: 6px 4px;
            background: var(--cd-bg);
            border-radius: 6px;
        }
        .cd-map-stat {
            text-align: center;
            flex: 1;
        }
        .cd-map-stat-value {
            font-weight: 800;
            font-size: 14px;
            color: var(--cd-text-main);
        }
        .cd-map-stat-label {
            font-size: 9px;
            font-weight: 600;
            color: var(--cd-text-muted);
            text-transform: uppercase;
        }

        .cd-activity-item {
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 6px 0;
            border-bottom: 1px solid var(--cd-border);
            font-size: 11px;
        }
        .cd-activity-dot {
            width: 6px;
            height: 6px;
            border-radius: 50%;
        }
        .cd-activity-dot.green { background: var(--cd-green); }
        .cd-activity-dot.yellow { background: var(--cd-yellow); }
        .cd-activity-dot.red { background: var(--cd-red); }
        .cd-activity-dot.gray { background: var(--cd-slate); }
        .cd-activity-dot.blue { background: var(--cd-blue); }
        .cd-activity-text { flex: 1; color: var(--cd-text-main); font-weight: 500; }
        .cd-activity-time { font-size: 9px; color: var(--cd-text-muted); }

        .btn-solid { background: var(--cd-red); color: white; border: none; padding: 8px 16px; border-radius: 6px; font-weight: 700; cursor: pointer; display: flex; align-items: center; gap: 6px; font-size: 12px; transition: 0.2s transform, 0.2s background; text-decoration: none; justify-content: center; }
        .btn-solid:hover { background: #dc2626; }
        .btn-solid:active { transform: scale(0.97); }
        .btn-outline { background: white; color: var(--cd-text-main); border: 1px solid var(--cd-border); padding: 8px 16px; border-radius: 6px; font-weight: 600; cursor: pointer; display: flex; align-items: center; gap: 6px; font-size: 12px; transition: 0.2s transform, 0.2s background; text-decoration: none; justify-content: center; }
        .btn-outline:hover { background: var(--cd-card-hover); }
        .btn-outline:active { transform: scale(0.97); }

        .cd-aqi-highlight { display: flex; align-items: center; gap: 12px; margin-bottom: 4px; }
        .cd-aqi-score { font-size: 28px; font-weight: 800; line-height: 1; }
        
        .aqi-good     { color: var(--cd-green); }
        .aqi-moderate { color: var(--cd-yellow); }
        .aqi-sensitive { color: var(--cd-orange); }
        .aqi-unhealthy { color: var(--cd-red); }
        .aqi-very-unhealthy { color: var(--cd-purple); }
        .aqi-hazardous { color: #7f1d1d; }

        .cd-progress-bar { width: 100%; height: 6px; background: var(--cd-border); border-radius: 4px; overflow: hidden; display: flex; }
        .cd-progress-fill.good { background: var(--cd-purple); }
        .cd-progress-fill.low { background: var(--cd-yellow); }
        .cd-progress-fill.offline { background: var(--cd-red); }
        
        /* Dashboard Marker Styles - MATCH MAP VIEW */
        .cd-dashboard-marker {
            width: 42px;
            height: 42px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 800;
            font-size: 11px;
            color: white;
            border: 3px solid white;
            box-shadow: 0 2px 8px rgba(0,0,0,0.3);
            cursor: pointer;
            transition: transform 0.2s;
            text-shadow: 0 1px 1px rgba(0,0,0,0.3);
        }
        .cd-dashboard-marker:hover {
            transform: scale(1.1);
            z-index: 1000;
        }
        .cd-dashboard-marker.good { background-color: #10b981; }
        .cd-dashboard-marker.moderate { background-color: #f59e0b; }
        .cd-dashboard-marker.sensitive { background-color: #f97316; }
        .cd-dashboard-marker.unhealthy { background-color: #ef4444; }
        .cd-dashboard-marker.very-unhealthy { background-color: #8b5cf6; }
        .cd-dashboard-marker.hazardous { background-color: #7f1d1d; }
        .cd-dashboard-marker.offline { background-color: #7f8c8d; opacity: 0.7; }

        /* Drilldown Panel - MATCH MAP VIEW */
        .cd-drilldown-panel {
            background: var(--cd-card-bg);
            border-radius: 6px;
            border: 1px solid var(--cd-border);
            margin-top: 8px;
            overflow: hidden;
        }
        .cd-panel-header {
            padding: 8px 12px;
            border-bottom: 1px solid var(--cd-border);
            background: #fdfbfb;
        }
        .cd-node-title-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .cd-node-name {
            font-size: 0.9rem;
            font-weight: 800;
        }
        .cd-status-pill {
            font-size: 0.6rem;
            font-weight: 800;
            padding: 2px 8px;
            border-radius: 12px;
            text-transform: uppercase;
        }
        .cd-status-pill.cd-good { background: #d1fae5; color: #065f46; }
        .cd-status-pill.cd-warning { background: #fef3c7; color: #92400e; }
        .cd-status-pill.cd-critical { background: #fee2e2; color: #991b1b; }
        .cd-node-meta-row {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            font-size: 0.65rem;
            margin-top: 6px;
            color: var(--cd-text-muted);
        }
        .cd-panel-body {
            padding: 10px 12px;
            max-height: 200px;
            overflow-y: auto;
        }
        .cd-section-title {
            font-size: 0.65rem;
            font-weight: 800;
            text-transform: uppercase;
            margin-bottom: 6px;
            color: var(--cd-text-muted);
        }
        .cd-pollutant-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 6px;
            margin-bottom: 10px;
        }
        .cd-pollutant-card {
            background: #f9fafb;
            border: 1px solid var(--cd-border);
            padding: 6px;
            border-radius: 4px;
            text-align: center;
        }
        .cd-pollutant-name {
            font-size: 0.65rem;
            color: var(--cd-text-muted);
        }
        .cd-pollutant-val {
            font-size: 0.85rem;
            font-weight: 800;
        }
        .cd-panel-footer {
            padding: 8px 12px;
            border-top: 1px solid var(--cd-border);
            background: #f9fafb;
            display: flex;
            gap: 8px;
        }
        .cd-btn-sm {
            flex: 1;
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 0.7rem;
            font-weight: 600;
            cursor: pointer;
            border: none;
        }
        .cd-btn-outline-sm {
            background: white;
            border: 1px solid var(--cd-border);
        }
        .cd-btn-danger-sm {
            background: white;
            border: 1px solid #fca5a5;
            color: var(--cd-red);
        }

        /* FLOATING ACTION MENU */
        .cd-floating-overlay {
            position: fixed;
            bottom: 24px;
            right: 24px;
            display: flex;
            flex-direction: column;
            align-items: flex-end;
            gap: 12px;
            z-index: 1000;
        }
        .cd-floating-menu {
            display: flex;
            flex-direction: column;
            align-items: flex-end;
            gap: 8px;
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            transform-origin: bottom right;
            opacity: 1;
            transform: scale(1) translateY(0);
        }
        .cd-floating-menu.hidden {
            opacity: 0;
            transform: scale(0.8) translateY(20px);
            pointer-events: none;
        }
        .cd-float-btn {
            background: var(--cd-card-bg);
            border: 1px solid var(--cd-border);
            box-shadow: 0 4px 12px rgba(0,0,0,0.08);
            border-radius: 50px;
            padding: 10px 18px;
            display: flex;
            align-items: center;
            gap: 8px;
            font-family: 'Inter', sans-serif;
            font-size: 12px;
            font-weight: 700;
            color: var(--cd-text-main);
            cursor: pointer;
            transition: 0.2s ease;
            white-space: nowrap;
            text-decoration: none;
        }
        .cd-float-btn:hover { transform: translateY(-2px); box-shadow: 0 6px 16px rgba(0,0,0,0.12); border-color: var(--cd-slate); }
        .cd-float-btn i { font-size: 16px; }
        .cd-float-btn.ai-btn { border: 2px solid var(--cd-cyan); background: #f0fdfa; color: #0e7490; margin-bottom: 8px; }
        .cd-float-btn.danger { color: var(--cd-red); border-color: rgba(239, 68, 68, 0.3); background: #fee2e2; }
        .cd-float-btn.danger:hover { background: var(--cd-red); color: white; }
        .cd-float-btn.master-btn {
            border-radius: 50%; width: 54px; height: 54px; padding: 0; justify-content: center;
            background: var(--cd-text-main); color: white; border: none;
            box-shadow: 0 4px 14px rgba(31, 41, 55, 0.4);
        }
        .cd-float-btn.master-btn i { font-size: 24px; transition: transform 0.3s; }
        .cd-float-btn.master-btn:hover { background: #111827; }
        .cd-floating-overlay.collapsed .master-btn i { transform: rotate(180deg); }

        /* Marker Cluster Styles */
        .marker-cluster-small {
            background-color: rgba(16, 185, 129, 0.6);
        }
        .marker-cluster-small div {
            background-color: rgba(16, 185, 129, 0.8);
        }
        .marker-cluster-medium {
            background-color: rgba(245, 158, 11, 0.6);
        }
        .marker-cluster-medium div {
            background-color: rgba(245, 158, 11, 0.8);
        }
        .marker-cluster-large {
            background-color: rgba(239, 68, 68, 0.6);
        }
        .marker-cluster-large div {
            background-color: rgba(239, 68, 68, 0.8);
        }

        @media (max-width: 1024px) {
            .cdashboard-environment, .cdashboard-system-health, .cdashboard-devices { grid-column: span 6; }
            .cdashboard-map, .cdashboard-network, .cdashboard-pipeline, .cdashboard-admin { grid-column: span 6; }
            .cd-incident-primary { flex-direction: column; align-items: flex-start; }
            .cd-incident-primary > div:last-child { width: 100%; display: flex; gap: 8px; }
            .cd-time-context-block { width: 100%; }
        }
        @media (max-width: 640px) {
            .cdashboard-wrapper > div { grid-column: span 12 !important; }
            .cd-time-context-block { grid-template-columns: 1fr; }
        }
    </style>

    <!-- Pass initial data from Django -->
    <script>
        window.CDASHBOARD_NODES = {{ all_nodes_data|safe|default:'[]' }};
        window.CDASHBOARD_USERS = {
            total: {{ user_stats.total_users|default:0 }},
            active: {{ user_stats.active_users|default:0 }},
            pending: {{ user_stats.pending_approval|default:0 }},
            admins: {{ user_stats.admin_count|default:0 }},
            officials: {{ user_stats.official_count|default:0 }},
            active_today: {{ user_stats.active_today|default:0 }},
            recent_activity: {{ recent_user_activity|safe|default:'[]' }}
        };
        window.CDASHBOARD_CONFIG = {
            mapCenter: [14.5631, 121.0192],
            mapZoom: 13,
            refreshInterval: 30000
        };
        
        console.log('[Dashboard] User stats from Django:', window.CDASHBOARD_USERS);
        console.log('[Dashboard] Nodes data length:', window.CDASHBOARD_NODES.length);
    </script>

    <div class="cdashboard-wrapper">

        {# ================================================================== #}
        {# PRIMARY INCIDENT CARD                                              #}
        {# ================================================================== #}
        {% with critical_alert=active_alerts.0 %}
        <div class="cd-incident-primary {% if not critical_alert %}clear{% endif %}">
            <div class="cd-incident-col">
                <div class="cd-incident-title {% if not critical_alert %}clear{% endif %}">
                    <i class="ph-fill {% if critical_alert %}ph-warning-circle{% else %}ph-check-circle{% endif %}" style="font-size: 18px;"></i>
                    {% if critical_alert %}
                        {{ critical_alert.title }}
                        <span class="cd-time-tag new">NEW</span>
                    {% else %}
                        All Systems Normal — No Active Incidents
                        <span class="cd-time-tag stable">CLEAR</span>
                    {% endif %}
                </div>

                <div class="cd-incident-detail">
                    {% if critical_alert %}
                        Node: {{ critical_alert.node.name }}
                        {% if critical_alert.node.location %} &mdash; {{ critical_alert.node.location }}{% endif %}
                    {% else %}
                        All sensor nodes are reporting within expected parameters.
                    {% endif %}
                </div>

                {% if critical_alert %}
                <div class="cd-trend critical" style="display: inline-flex; width: fit-content; margin-top: 4px;">
                    <i class="ph-bold ph-trend-up"></i>
                    Severity: {{ critical_alert.get_severity_display }} &mdash; Avg AQI: {{ aggregate_data.avg_aqi|default:"N/A" }}
                </div>
                {% endif %}
            </div>

            <div class="cd-incident-col" style="flex: 1; max-width: 450px;">
                <div class="cd-incident-impact">
                    <div>Nodes Offline: <span id="globalOfflineCount">{{ system_health.inactive_nodes }}</span></div>
                    <div>Active: <span id="globalActiveCount">{{ system_health.active_nodes }} / {{ system_health.total_nodes }}</span></div>
                    <div>
                        Alerts:
                        <span style="color: {% if severity_counts.critical > 0 %}var(--cd-red){% elif severity_counts.warning > 0 %}var(--cd-yellow){% else %}var(--cd-green){% endif %};">
                            {% if severity_counts.critical > 0 %}
                                {{ severity_counts.critical }} Critical
                            {% elif severity_counts.warning > 0 %}
                                {{ severity_counts.warning }} Warning{{ severity_counts.warning|pluralize }}
                            {% else %}
                                None
                            {% endif %}
                        </span>
                    </div>
                </div>

                <div class="cd-time-context-block {% if not critical_alert %}clear{% endif %}" style="margin-top: 4px;">
                    <div>
                        Last Reading:
                        <span>
                            <i class="ph-bold ph-clock"></i>
                            {% if system_health.data_freshness_minutes is not None %}
                                {{ system_health.data_freshness_minutes }} min ago
                            {% else %}
                                No data yet
                            {% endif %}
                        </span>
                    </div>
                    <div>
                        Time:
                        <span>
                            <i class="ph-bold ph-arrows-clockwise"></i>
                            {% if system_health.latest_reading_time %}
                                {{ system_health.latest_reading_time|date:"H:i" }}
                            {% else %}
                                &mdash;
                            {% endif %}
                        </span>
                    </div>
                    <div>
                        Warnings:
                        <span>
                            <i class="ph-bold ph-warning"></i>
                            {{ severity_counts.warning }} active
                        </span>
                    </div>
                    <div>
                        Info Alerts:
                        <span>
                            <i class="ph-bold ph-info"></i>
                            {{ severity_counts.info }} active
                        </span>
                    </div>
                </div>
            </div>

            <div style="display: flex; flex-direction: column; gap: 8px; min-width: 140px;">
                <a href="{% url 'app:client_alerts' %}" class="btn-solid">
                    <i class="ph-bold ph-crosshair"></i>
                    {% if critical_alert %}Investigate{% else %}View Alerts{% endif %}
                </a>
                <a href="{% url 'app:client_devices' %}" class="btn-outline">
                    View Devices
                </a>
            </div>
        </div>
        {% endwith %}

        {# ================================================================== #}
        {# SECONDARY ISSUES STRIP                                             #}
        {# ================================================================== #}
        <div class="cd-secondary-issues">
            {% if severity_counts.critical > 0 %}
            <a href="{% url 'app:client_alerts' %}" class="cd-secondary-pill orange" style="text-decoration: none;">
                <i class="ph-fill ph-warning-circle" style="color: var(--cd-red);"></i>
                {{ severity_counts.critical }} Critical Alert{{ severity_counts.critical|pluralize }}
            </a>
            {% endif %}

            {% if severity_counts.warning > 0 %}
            <a href="{% url 'app:client_alerts' %}" class="cd-secondary-pill yellow" style="text-decoration: none;">
                <i class="ph-fill ph-warning" style="color: var(--cd-yellow);"></i>
                {{ severity_counts.warning }} Warning{{ severity_counts.warning|pluralize }}
            </a>
            {% endif %}

            {% if system_health.inactive_nodes > 0 %}
            <a href="{% url 'app:client_devices' %}" class="cd-secondary-pill orange" style="text-decoration: none;">
                <i class="ph-fill ph-wifi-slash" style="color: var(--cd-orange);"></i>
                {{ system_health.inactive_nodes }} Node{{ system_health.inactive_nodes|pluralize }} Offline
            </a>
            {% endif %}

            <div class="cd-secondary-pill yellow" id="pendingUsersPill" style="display: {% if user_stats.pending_approval > 0 %}flex{% else %}none{% endif %};">
                <i class="ph-fill ph-user-circle-plus" style="color: var(--cd-yellow);"></i>
                <span id="pendingUsersCount">{{ user_stats.pending_approval }}</span> User{{ user_stats.pending_approval|pluralize }} Awaiting Approval
            </div>

            {% if severity_counts.critical == 0 and severity_counts.warning == 0 and system_health.inactive_nodes == 0 and user_stats.pending_approval == 0 %}
            <div class="cd-secondary-pill green">
                <i class="ph-fill ph-check-circle"></i>
                No secondary issues detected — all systems nominal
            </div>
            {% endif %}
        </div>

        {# ================================================================== #}
        {# ENVIRONMENT IMPACT CARD                                            #}
        {# ================================================================== #}
        <div class="cdashboard-card cdashboard-environment">
            <div class="cdashboard-card-header">
                <div class="cd-header-left">
                    <i class="ph-fill ph-leaf" style="color: var(--cd-yellow);"></i> Environment Impact
                </div>
                {% if aggregate_data.avg_aqi > 150 %}
                    <span class="cd-time-tag new">ALERT</span>
                {% elif aggregate_data.avg_aqi > 50 %}
                    <span class="cd-time-tag ongoing">ONGOING</span>
                {% else %}
                    <span class="cd-time-tag stable">STABLE</span>
                {% endif %}
            </div>
            <div class="cdashboard-card-body">

                <div class="cd-confidence-bar">
                    <span class="cd-confidence-text">
                        <i class="ph-bold ph-shield-check"></i> Live Avg AQI
                    </span>
                    <span class="cd-confidence-val {% if aggregate_data.avg_aqi > 100 %}degraded{% else %}high{% endif %}">
                        {% if aggregate_data.avg_aqi > 150 %}Unhealthy
                        {% elif aggregate_data.avg_aqi > 100 %}Moderate Risk
                        {% elif aggregate_data.avg_aqi > 0 %}Good
                        {% else %}No Data
                        {% endif %}
                    </span>
                </div>

                <div class="cd-aqi-highlight">
                    <div class="cd-aqi-score
                        {% if aggregate_data.avg_aqi <= 50 %}aqi-good
                        {% elif aggregate_data.avg_aqi <= 100 %}aqi-moderate
                        {% elif aggregate_data.avg_aqi <= 150 %}aqi-sensitive
                        {% elif aggregate_data.avg_aqi <= 200 %}aqi-unhealthy
                        {% elif aggregate_data.avg_aqi <= 300 %}aqi-very-unhealthy
                        {% else %}aqi-hazardous
                        {% endif %}
                        shimmer-text"
                        data-tooltip="Based on {{ active_count }} active node{{ active_count|pluralize }}">
                        {{ aggregate_data.avg_aqi|default:"—" }}
                    </div>
                    <div>
                        <div style="font-weight: 700; color: var(--cd-text-main);">
                            Avg AQI
                            ({% if aggregate_data.avg_aqi <= 50 %}Good
                            {% elif aggregate_data.avg_aqi <= 100 %}Moderate
                            {% elif aggregate_data.avg_aqi <= 150 %}Unhealthy for Sensitive Groups
                            {% elif aggregate_data.avg_aqi <= 200 %}Unhealthy
                            {% elif aggregate_data.avg_aqi <= 300 %}Very Unhealthy
                            {% elif aggregate_data.avg_aqi > 300 %}Hazardous
                            {% else %}No Data
                            {% endif %})
                        </div>
                        <div style="font-size: 11px; color: var(--cd-text-muted); margin-top: 2px;">
                            PM2.5 avg: {{ aggregate_data.avg_pm2_5|default:"—" }} µg/m³
                        </div>
                    </div>
                </div>

                <div class="cd-metric-row">
                    <span class="cd-metric-label">Nodes Reporting</span>
                    <span class="cd-metric-val" id="envNodesReporting">
                        {{ active_count }} / {{ total_nodes }}
                        {% if inactive_count > 0 %}
                            <span class="cd-pill red">{{ inactive_count }} Offline</span>
                        {% else %}
                            <span class="cd-pill green">All Online</span>
                        {% endif %}
                    </span>
                </div>

                <div class="cd-metric-row">
                    <span class="cd-metric-label">7-Day AQI Range</span>
                    <span class="cd-metric-val">
                        {{ analytics.min_aqi|default:"—" }} &ndash; {{ analytics.max_aqi|default:"—" }}
                    </span>
                </div>

                <div class="cd-metric-row">
                    <span class="cd-metric-label">Avg Temperature</span>
                    <span class="cd-metric-val">
                        {% if analytics.avg_temperature %}
                            {{ analytics.avg_temperature }} &deg;C
                        {% else %}
                            &mdash;
                        {% endif %}
                    </span>
                </div>

                <div class="cd-link-hint">
                    <i class="ph-fill ph-link"></i>
                    {% if analytics.avg_pm2_5 %}
                        7-day avg PM2.5: {{ analytics.avg_pm2_5 }} µg/m³ across {{ analytics.total_readings }} readings.
                    {% else %}
                        No readings in the last 7 days. Check node connectivity.
                    {% endif %}
                </div>
            </div>
            <a href="{% url 'app:client_analytics' %}" class="cdashboard-quick-access">
                View Full Analytics &rarr;
            </a>
        </div>

        {# ================================================================== #}
        {# SYSTEM HEALTH CARD                                                 #}
        {# ================================================================== #}
        <div class="cdashboard-card cdashboard-system-health">
            <div class="cdashboard-card-header">
                <div class="cd-header-left">
                    <i class="ph-fill ph-heartbeat" style="color: var(--cd-green);"></i> System Health
                </div>
                {% if system_health.inactive_nodes == 0 and severity_counts.critical == 0 %}
                    <span class="cd-time-tag stable">HEALTHY</span>
                {% elif severity_counts.critical > 0 %}
                    <span class="cd-time-tag new">CRITICAL</span>
                {% else %}
                    <span class="cd-time-tag ongoing">DEGRADED</span>
                {% endif %}
            </div>
            <div class="cdashboard-card-body">

                <div class="cd-confidence-bar"
                    {% if system_health.inactive_nodes == 0 %}
                        style="border-color: var(--cd-green); background: var(--cd-green-bg);"
                    {% else %}
                        style="border-color: var(--cd-yellow); background: var(--cd-yellow-bg);"
                    {% endif %}>
                    <span class="cd-confidence-text"
                        {% if system_health.inactive_nodes == 0 %}
                            style="color: var(--cd-green);"
                        {% else %}
                            style="color: var(--cd-yellow-text);"
                        {% endif %}>
                        <i class="ph-bold ph-activity"></i> System Confidence
                    </span>
                    <span class="cd-confidence-val {% if system_health.inactive_nodes == 0 %}high{% else %}degraded{% endif %}">
                        {% if system_health.inactive_nodes == 0 %}High{% else %}Medium{% endif %}
                    </span>
                </div>

                <div class="cd-metric-row">
                    <span class="cd-metric-label">Total Nodes</span>
                    <span class="cd-metric-val shimmer-text">{{ system_health.total_nodes }}</span>
                </div>

                <div class="cd-metric-row">
                    <span class="cd-metric-label">Active Nodes</span>
                    <span class="cd-metric-val" id="healthActiveNodes"
                        data-tooltip="{{ system_health.inactive_nodes }} offline node{{ system_health.inactive_nodes|pluralize }} reducing coverage">
                        {{ system_health.active_nodes }} / {{ system_health.total_nodes }}
                        {% if system_health.inactive_nodes > 0 %}
                            <span class="cd-pill red">{{ system_health.inactive_nodes }} Down</span>
                        {% else %}
                            <span class="cd-pill green">All Up</span>
                        {% endif %}
                    </span>
                </div>

                <div class="cd-metric-row">
                    <span class="cd-metric-label">Data Freshness</span>
                    <span class="cd-metric-val">
                        {% if system_health.data_freshness_minutes is not None %}
                            {% if system_health.data_freshness_minutes < 5 %}
                                <span style="color: var(--cd-green);">
                                    <i class="ph-fill ph-circle" style="font-size:8px;"></i>
                                    Live ({{ system_health.data_freshness_minutes }}m ago)
                                </span>
                            {% elif system_health.data_freshness_minutes < 30 %}
                                <span style="color: var(--cd-yellow);">
                                    {{ system_health.data_freshness_minutes }}m ago
                                </span>
                            {% else %}
                                <span style="color: var(--cd-red);">
                                    Stale ({{ system_health.data_freshness_minutes }}m ago)
                                </span>
                            {% endif %}
                        {% else %}
                            <span style="color: var(--cd-text-muted);">No readings yet</span>
                        {% endif %}
                    </span>
                </div>

                <div class="cd-link-hint">
                    <i class="ph-fill ph-link"></i>
                    <span id="healthLinkHint">
                        {% if system_health.inactive_nodes > 0 %}
                            {{ system_health.inactive_nodes }} offline node{{ system_health.inactive_nodes|pluralize }} reducing AQI accuracy.
                        {% else %}
                            All nodes online — data confidence is high.
                        {% endif %}
                    </span>
                </div>
            </div>
            <a href="{% url 'app:client_devices' %}" class="cdashboard-quick-access {% if system_health.inactive_nodes > 0 %}urgent{% endif %}">
                {% if system_health.inactive_nodes > 0 %}
                    View Offline Nodes ({{ system_health.inactive_nodes }}) &rarr;
                {% else %}
                    View All Devices &rarr;
                {% endif %}
            </a>
        </div>

        {# ================================================================== #}
        {# SENSOR HARDWARE / DEVICES CARD                                     #}
        {# ================================================================== #}
        <div class="cdashboard-card cdashboard-devices">
            <div class="cdashboard-card-header">
                <div class="cd-header-left">
                    <i class="ph-fill ph-cpu" style="color: var(--cd-purple);"></i> Sensor Hardware
                </div>
                {% if inactive_count > 0 %}
                    <span class="cd-time-tag ongoing">ATTENTION</span>
                {% else %}
                    <span class="cd-time-tag stable">OK</span>
                {% endif %}
            </div>
            <div class="cdashboard-card-body">

                {% if total_nodes > 0 %}
                <div>
                    <div class="cd-metric-row" style="margin-bottom: 6px;">
                        <span class="cd-metric-label">Node Fleet Status</span>
                    </div>
                    <div class="cd-progress-bar"
                        data-tooltip="{{ active_count }} active, {{ inactive_count }} offline out of {{ total_nodes }} total">
                        {% if active_count > 0 %}
                        <div class="cd-progress-fill good"
                            style="width: {% widthratio active_count total_nodes 100 %}%;">
                        </div>
                        {% endif %}
                        {% if inactive_count > 0 %}
                        <div class="cd-progress-fill offline"
                            style="width: {% widthratio inactive_count total_nodes 100 %}%;">
                        </div>
                        {% endif %}
                    </div>
                    <div style="display: flex; justify-content: space-between; font-size: 10px; font-weight: 700; margin-top: 6px;">
                        <span style="color: var(--cd-purple);">{{ active_count }} Active</span>
                        <span style="color: var(--cd-red);">{{ inactive_count }} Offline</span>
                        <span style="color: var(--cd-slate);">{{ total_nodes }} Total</span>
                    </div>
                </div>
                {% else %}
                <div style="text-align: center; color: var(--cd-text-muted); font-size: 12px; padding: 12px 0;">
                    No sensor nodes registered yet.
                </div>
                {% endif %}

                <div class="cd-metric-row" style="margin-top: 4px;">
                    <span class="cd-metric-label">Readings (7 days)</span>
                    <span class="cd-metric-val">
                        {{ analytics.total_readings|default:"0" }}
                        {% if analytics.total_readings > 0 %}
                            <span class="cd-trend good">↑ Ingesting</span>
                        {% else %}
                            <span class="cd-trend slow">— No data</span>
                        {% endif %}
                    </span>
                </div>

                <div class="cd-link-hint">
                    <i class="ph-fill ph-link"></i>
                    {% if inactive_count > 0 %}
                        {{ inactive_count }} offline node{{ inactive_count|pluralize }} may be affecting AQI coverage.
                    {% else %}
                        All nodes reporting normally.
                    {% endif %}
                </div>
            </div>
            <a href="{% url 'app:client_devices' %}" class="cdashboard-quick-access {% if inactive_count > 0 %}urgent{% endif %}">
                {% if inactive_count > 0 %}
                    View Offline Nodes ({{ inactive_count }}) &rarr;
                {% else %}
                    Manage Devices &rarr;
                {% endif %}
            </a>
        </div>

        {# ================================================================== #}
        {# SPATIAL CONTEXT / MAP CARD - MATCH MAP VIEW                        #}
        {# ================================================================== #}
        <div class="cdashboard-card cdashboard-map">
            <div class="cdashboard-card-header">
                <div class="cd-header-left">
                    <i class="ph-fill ph-map-pin" style="color: var(--cd-slate);"></i> Spatial Context
                </div>
                <span id="mapStatusTag" class="cd-time-tag stable">LIVE</span>
            </div>
            <div class="cdashboard-card-body" style="padding: 10px;">
                <div class="cd-real-map-container">
                    <div id="cdashboard-real-map" class="cd-real-map"></div>
                    
                    <!-- Map Controls - Floating Panel -->
                    <div class="cd-map-controls">
                        <div class="cd-control-group">
                            <label class="cd-control-label">Data Layer</label>
                            <select class="cd-select-input" id="cd-layer-select">
                                <option value="aqi">AQI (Overall)</option>
                                <option value="pm25">PM 2.5</option>
                                <option value="pm10">PM 10</option>
                                <option value="temperature">Temperature</option>
                            </select>
                        </div>
                        <div class="cd-control-group">
                            <label class="cd-control-label">Node Visibility</label>
                            <div class="cd-toggle-row">
                                <span>Online</span>
                                <div class="cd-toggle-switch" id="cd-toggle-active"></div>
                            </div>
                            <div class="cd-toggle-row">
                                <span>Offline</span>
                                <div class="cd-toggle-switch" id="cd-toggle-inactive"></div>
                            </div>
                        </div>
                        <div class="cd-control-group">
                            <label class="cd-control-label">Timeframe</label>
                            <div class="cd-btn-group">
                                <button class="cd-active" id="cd-btn-live">Live</button>
                                <button id="cd-btn-24h">Last 24h</button>
                            </div>
                        </div>
                    </div>
                    
                    <!-- Map Legend -->
                    <div class="cd-map-legend" id="cd-map-legend">
                        <span class="cd-legend-title">AQI</span>
                        <div class="cd-legend-item"><div class="cd-legend-color" style="background: #10b981;"></div> Good</div>
                        <div class="cd-legend-item"><div class="cd-legend-color" style="background: #f59e0b;"></div> Mod</div>
                        <div class="cd-legend-item"><div class="cd-legend-color" style="background: #f97316;"></div> Sens</div>
                        <div class="cd-legend-item"><div class="cd-legend-color" style="background: #ef4444;"></div> Unh</div>
                        <div class="cd-legend-item"><div class="cd-legend-color" style="background: #7f1d1d;"></div> Haz</div>
                    </div>
                </div>
                
                <div class="cd-map-stats">
                    <div class="cd-map-stat">
                        <div class="cd-map-stat-value" id="mapActiveCount">0</div>
                        <div class="cd-map-stat-label">Active Nodes</div>
                    </div>
                    <div class="cd-map-stat">
                        <div class="cd-map-stat-value" id="mapOfflineCount">0</div>
                        <div class="cd-map-stat-label">Offline</div>
                    </div>
                    <div class="cd-map-stat">
                        <div class="cd-map-stat-value" id="mapAvgAqi">—</div>
                        <div class="cd-map-stat-label">Avg AQI</div>
                    </div>
                </div>

                <!-- Drilldown Panel -->
                <div id="cd-drilldown-panel" class="cd-drilldown-panel">
                    <div class="cd-panel-header">
                        <div class="cd-node-title-row">
                            <div class="cd-node-name" id="dd-node-name">Select a node</div>
                            <span class="cd-status-pill" id="dd-status">—</span>
                        </div>
                        <div class="cd-node-meta-row" id="dd-meta">
                            <span>📍 Loading...</span>
                        </div>
                    </div>
                    <div class="cd-panel-body" id="dd-body">
                        <div class="cd-section-title">Sensor Telemetry</div>
                        <div class="cd-pollutant-grid">
                            <div class="cd-pollutant-card">
                                <div class="cd-pollutant-name">AQI</div>
                                <div class="cd-pollutant-val" id="dd-aqi">—</div>
                            </div>
                            <div class="cd-pollutant-card">
                                <div class="cd-pollutant-name">PM2.5</div>
                                <div class="cd-pollutant-val" id="dd-pm25">—</div>
                            </div>
                            <div class="cd-pollutant-card">
                                <div class="cd-pollutant-name">PM10</div>
                                <div class="cd-pollutant-val" id="dd-pm10">—</div>
                            </div>
                            <div class="cd-pollutant-card">
                                <div class="cd-pollutant-name">Temperature</div>
                                <div class="cd-pollutant-val" id="dd-temp">—</div>
                            </div>
                        </div>
                        <div class="cd-section-title">Last Seen</div>
                        <div class="cd-activity-item" id="dd-last-seen">
                            <span class="cd-activity-text">Loading...</span>
                        </div>
                    </div>
                    <div class="cd-panel-footer">
                        <button class="cd-btn-sm cd-btn-outline-sm" id="dd-view-map">View on Map</button>
                    </div>
                </div>
            </div>
            <a href="{% url 'app:client_map' %}" class="cdashboard-quick-access">
                Open Full Map &rarr;
            </a>
        </div>

        {# ================================================================== #}
        {# DATA PIPELINE CARD                                                 #}
        {# ================================================================== #}
        <div class="cdashboard-card cdashboard-pipeline">
            <div class="cdashboard-card-header">
                <div class="cd-header-left">
                    <i class="ph-fill ph-database" style="color: var(--cd-orange);"></i> Data Pipeline
                </div>
                {% if analytics.total_readings > 0 %}
                    <span class="cd-time-tag stable">STABLE</span>
                {% else %}
                    <span class="cd-time-tag ongoing">NO DATA</span>
                {% endif %}
            </div>
            <div class="cdashboard-card-body">
                <div class="cd-metric-row">
                    <span class="cd-metric-label">Readings (7 days)</span>
                    <span class="cd-metric-val">{{ analytics.total_readings|default:"0" }}</span>
                </div>
                <div class="cd-metric-row">
                    <span class="cd-metric-label">Avg PM2.5 (7d)</span>
                    <span class="cd-metric-val">
                        {% if analytics.avg_pm2_5 %}
                            {{ analytics.avg_pm2_5 }} µg/m³
                        {% else %}
                            &mdash;
                        {% endif %}
                    </span>
                </div>
                <div class="cd-metric-row">
                    <span class="cd-metric-label">AQI Min / Max (7d)</span>
                    <span class="cd-metric-val">
                        {{ analytics.min_aqi|default:"—" }} / {{ analytics.max_aqi|default:"—" }}
                    </span>
                </div>
                <div class="cd-link-hint">
                    <i class="ph-fill ph-link"></i>
                    {% if analytics.total_readings > 0 %}
                        Pipeline ingesting normally across {{ active_count }} active node{{ active_count|pluralize }}.
                    {% else %}
                        No readings in the last 7 days — check node connectivity.
                    {% endif %}
                </div>
            </div>
            <a href="{% url 'app:client_analytics' %}" class="cdashboard-quick-access">
                View Analytics &rarr;
            </a>
        </div>

        {# ================================================================== #}
        {# USERS / PERSONNEL CARD                                             #}
        {# ================================================================== #}
        <div class="cdashboard-card cdashboard-network">
            <div class="cdashboard-card-header">
                <div class="cd-header-left">
                    <i class="ph-fill ph-users" style="color: var(--cd-blue);"></i> Users
                </div>
                <span id="userStatusTag" class="cd-time-tag {% if user_stats.pending_approval > 0 %}ongoing{% else %}stable{% endif %}">
                    {% if user_stats.pending_approval > 0 %}ACTION NEEDED{% else %}OK{% endif %}
                </span>
            </div>
            <div class="cdashboard-card-body">
                <div class="cd-metric-row">
                    <span class="cd-metric-label">Total Users</span>
                    <span class="cd-metric-val shimmer-text" id="userTotalCount">{{ user_stats.total_users|default:"0" }}</span>
                </div>
                <div class="cd-metric-row">
                    <span class="cd-metric-label">Admins / Officials</span>
                    <span class="cd-metric-val" id="userRoleCount">
                        {{ user_stats.admin_count|default:"0" }} / {{ user_stats.official_count|default:"0" }}
                    </span>
                </div>
                <div class="cd-metric-row">
                    <span class="cd-metric-label">Pending Approval</span>
                    <span class="cd-metric-val" id="userPendingCount">
                        {{ user_stats.pending_approval|default:"0" }}
                        {% if user_stats.pending_approval > 0 %}
                            <span class="cd-pill red">Review Required</span>
                        {% else %}
                            <span class="cd-trend good">↑ All Approved</span>
                        {% endif %}
                    </span>
                </div>
                <div class="cd-metric-row">
                    <span class="cd-metric-label">Active Today</span>
                    <span class="cd-metric-val" id="userActiveToday">
                        {% if user_stats.active_today %}
                            {{ user_stats.active_today }}
                        {% else %}
                            0
                        {% endif %}
                        <span class="cd-trend good">Active</span>
                    </span>
                </div>
                <div id="userRecentActivity" class="cd-recent-activity" style="margin-top: 8px;"></div>
                <div class="cd-link-hint">
                    <i class="ph-fill ph-link"></i>
                    <span id="userLinkHint">
                        {% if user_stats.pending_approval > 0 %}
                            {{ user_stats.pending_approval }} user{{ user_stats.pending_approval|pluralize }} awaiting admin approval.
                        {% else %}
                            All registered users are approved and active.
                        {% endif %}
                    </span>
                </div>
            </div>
            <a href="{% url 'app:client_users' %}" class="cdashboard-quick-access {% if user_stats.pending_approval > 0 %}urgent{% endif %}" id="userManageLink">
                Manage Users &rarr;
            </a>
        </div>

        {# ================================================================== #}
        {# ALERTS SUMMARY CARD                                                #}
        {# ================================================================== #}
        <div class="cdashboard-card cdashboard-admin">
            <div class="cdashboard-card-header">
                <div class="cd-header-left">
                    <i class="ph-fill ph-bell-ringing" style="color: var(--cd-red);"></i> Alert Summary
                </div>
                {% if severity_counts.critical > 0 %}
                    <span class="cd-time-tag new">CRITICAL</span>
                {% elif severity_counts.warning > 0 %}
                    <span class="cd-time-tag ongoing">WARNING</span>
                {% else %}
                    <span class="cd-time-tag stable">CLEAR</span>
                {% endif %}
            </div>
            <div class="cdashboard-card-body">
                <div class="cd-metric-row">
                    <span class="cd-metric-label">Critical</span>
                    <span class="cd-metric-val" style="color: {% if severity_counts.critical > 0 %}var(--cd-red){% else %}var(--cd-text-muted){% endif %};">
                        {{ severity_counts.critical|default:"0" }}
                    </span>
                </div>
                <div class="cd-metric-row">
                    <span class="cd-metric-label">Warnings</span>
                    <span class="cd-metric-val" style="color: {% if severity_counts.warning > 0 %}var(--cd-yellow-text){% else %}var(--cd-text-muted){% endif %};">
                        {{ severity_counts.warning|default:"0" }}
                    </span>
                </div>
                <div class="cd-metric-row">
                    <span class="cd-metric-label">Info</span>
                    <span class="cd-metric-val">{{ severity_counts.info|default:"0" }}</span>
                </div>
                <div class="cd-link-hint">
                    <i class="ph-fill ph-link"></i>
                    {% if severity_counts.critical > 0 %}
                        {{ severity_counts.critical }} critical alert{{ severity_counts.critical|pluralize }} require immediate attention.
                    {% elif severity_counts.warning > 0 %}
                        {{ severity_counts.warning }} warning{{ severity_counts.warning|pluralize }} need review.
                    {% else %}
                        No active alerts — system is operating normally.
                    {% endif %}
                </div>
            </div>
            <a href="{% url 'app:client_alerts' %}" class="cdashboard-quick-access {% if severity_counts.critical > 0 %}urgent{% endif %}">
                View All Alerts &rarr;
            </a>
        </div>

    </div>

    {# ================================================================== #}
    {# FLOATING QUICK-ACTION MENU                                          #}
    {# ================================================================== #}
    <div class="cd-floating-overlay" id="floatingOverlay">
        <div class="cd-floating-menu hidden" id="floatingMenu">
            <a href="{% url 'app:client_alerts' %}" class="cd-float-btn ai-btn">
                <i class="ph-fill ph-sparkle"></i> View Active Alerts
            </a>
            <a href="{% url 'app:client_devices' %}" class="cd-float-btn">
                <i class="ph-bold ph-activity"></i> Check Devices
            </a>
            <a href="{% url 'app:client_map' %}" class="cd-float-btn">
                <i class="ph-bold ph-broadcast"></i> Live Map
            </a>
            <a href="{% url 'app:client_analytics' %}" class="cd-float-btn">
                <i class="ph-bold ph-chart-line"></i> Analytics
            </a>
        </div>

        <button class="cd-float-btn master-btn" onclick="toggleFloatingMenu()" title="Toggle Quick Actions">
            <i class="ph-bold ph-list-plus" id="masterIcon"></i>
        </button>
    </div>

    <script>
        function toggleFloatingMenu() {
            const menu = document.getElementById('floatingMenu');
            const overlay = document.getElementById('floatingOverlay');
            const icon = document.getElementById('masterIcon');
            
            menu.classList.toggle('hidden');
            overlay.classList.toggle('collapsed');
            
            if (menu.classList.contains('hidden')) {
                icon.classList.remove('ph-x');
                icon.classList.add('ph-list-plus');
            } else {
                icon.classList.remove('ph-list-plus');
                icon.classList.add('ph-x');
            }
        }
    </script>

    {# ================================================================== #}
    {# DEDICATED JAVASCRIPT - DASHBOARD SPATIAL CONTEXT (FULL MAP VIEW)   #}
    {# ================================================================== #}
    <script>
    (function() {
        'use strict';

        // ================================================================
        // DASHBOARD MAP CONTROLLER (Matches Map View functionality)
        // ================================================================
        
        let dashboardMap = null;
        let markerLayerGroup = null;
        let markersByNodeId = new Map();
        let currentLayer = 'aqi';
        let overlays = { active: true, inactive: true };
        let timeframe = 'live';
        let selectedNodeId = null;
        let allNodesData = [];
        
        // Helper: Get AQI color class
        function getAqiColorClass(aqi) {
            if (aqi === null || aqi === undefined) return 'offline';
            if (aqi <= 50) return 'good';
            if (aqi <= 100) return 'moderate';
            if (aqi <= 150) return 'sensitive';
            if (aqi <= 200) return 'unhealthy';
            if (aqi <= 300) return 'very-unhealthy';
            return 'hazardous';
        }
        
        // Helper: Get marker color based on layer and value
        function getMarkerColor(layer, value, isActive) {
            if (!isActive) return '#7f8c8d';
            if (value === null || value === undefined) return '#f59e0b';
            
            if (layer === 'aqi') {
                if (value <= 50) return '#10b981';
                if (value <= 100) return '#f59e0b';
                if (value <= 150) return '#f97316';
                if (value <= 200) return '#ef4444';
                if (value <= 300) return '#8b5cf6';
                return '#7f1d1d';
            }
            if (layer === 'pm25') {
                if (value <= 12) return '#10b981';
                if (value <= 35) return '#f59e0b';
                if (value <= 55) return '#f97316';
                if (value <= 150) return '#ef4444';
                return '#7f1d1d';
            }
            if (layer === 'pm10') {
                if (value <= 54) return '#10b981';
                if (value <= 154) return '#f59e0b';
                if (value <= 254) return '#f97316';
                if (value <= 354) return '#ef4444';
                return '#7f1d1d';
            }
            if (layer === 'temperature') {
                if (value < 25) return '#10b981';
                if (value <= 30) return '#f59e0b';
                if (value <= 35) return '#f97316';
                if (value <= 40) return '#ef4444';
                return '#7f1d1d';
            }
            return '#10b981';
        }
        
        // Helper: Format relative time
        function formatRelativeTime(timestamp) {
            if (!timestamp) return 'Never';
            const date = new Date(timestamp);
            if (isNaN(date.getTime())) return 'Unknown';
            const now = new Date();
            const diffMins = Math.floor((now - date) / 60000);
            if (diffMins < 1) return 'Just now';
            if (diffMins < 60) return `${diffMins}m ago`;
            const diffHours = Math.floor(diffMins / 60);
            if (diffHours < 24) return `${diffHours}h ago`;
            return `${Math.floor(diffHours / 24)}d ago`;
        }
        
        // Initialize map
        function initMap() {
            const mapContainer = document.getElementById('cdashboard-real-map');
            if (!mapContainer) return;
            
            if (dashboardMap) {
                dashboardMap.remove();
                dashboardMap = null;
            }
            
            dashboardMap = L.map(mapContainer).setView([14.5631, 121.0192], 13);
            
            L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                maxZoom: 19,
                attribution: '© OpenStreetMap contributors'
            }).addTo(dashboardMap);
            
            // Create marker cluster group
            markerLayerGroup = L.markerClusterGroup({
                maxClusterRadius: 50,
                disableClusteringAtZoom: 16,
                spiderfyOnMaxZoom: true
            });
            markerLayerGroup.addTo(dashboardMap);
            
            console.log('[Dashboard Map] Initialized');
        }
        
        // Create marker
        function createMarker(node, isActive) {
            const lat = node.latitude || node.lat;
            const lng = node.longitude || node.lng;
            if (!lat || !lng) return null;
            
            let value = null;
            if (currentLayer === 'aqi') value = node.aqi;
            else if (currentLayer === 'pm25') value = node.pm2_5;
            else if (currentLayer === 'pm10') value = node.pm10;
            else if (currentLayer === 'temperature') value = node.temperature;
            
            const color = getMarkerColor(currentLayer, value, isActive);
            const displayValue = (value !== null && value !== undefined) ? Math.round(value) : 'N/A';
            const colorClass = getAqiColorClass(node.aqi);
            
            const markerHtml = `<div class="cd-dashboard-marker ${colorClass}" style="background-color: ${color} !important;">${displayValue}</div>`;
            const icon = L.divIcon({
                html: markerHtml,
                className: '',
                iconSize: [42, 42],
                popupAnchor: [0, -21]
            });
            
            const marker = L.marker([lat, lng], { icon: icon });
            marker.nodeData = node;
            marker.nodeId = node.id;
            
            const popupContent = `
                <div style="padding: 8px; min-width: 180px;">
                    <strong>${node.name || 'Unknown Node'}</strong><br>
                    <span style="font-size: 11px; color: #666;">📍 ${node.location || 'Unknown'}</span><br>
                    <span style="font-size: 11px;">AQI: <strong style="color: ${getMarkerColor('aqi', node.aqi, true)};">${node.aqi !== null ? Math.round(node.aqi) : 'N/A'}</strong></span><br>
                    <span style="font-size: 10px; color: #888;">Status: ${isActive ? '✅ Active' : '⚠️ Offline'}</span>
                </div>
            `;
            marker.bindPopup(popupContent);
            
            marker.on('click', () => selectNode(node.id));
            
            return marker;
        }
        
        // Render all markers
        function renderMarkers() {
            if (!dashboardMap || !markerLayerGroup) return;
            
            markerLayerGroup.clearLayers();
            markersByNodeId.clear();
            
            const nodes = window.CDASHBOARD_NODES || [];
            
            if (!nodes || nodes.length === 0) {
                document.getElementById('mapActiveCount').textContent = '0';
                document.getElementById('mapOfflineCount').textContent = '0';
                document.getElementById('mapAvgAqi').textContent = '—';
                return;
            }
            
            let activeCount = 0;
            let offlineCount = 0;
            let totalAqi = 0;
            let aqiCount = 0;
            
            nodes.forEach(node => {
                const isActive = node.status === 'active' || node.status === 'online';
                const shouldShow = (isActive && overlays.active) || (!isActive && overlays.inactive);
                
                if (!shouldShow) return;
                
                if (isActive) activeCount++;
                else offlineCount++;
                
                if (node.aqi !== null && !isNaN(node.aqi)) {
                    totalAqi += node.aqi;
                    aqiCount++;
                }
                
                const marker = createMarker(node, isActive);
                if (marker) {
                    markerLayerGroup.addLayer(marker);
                    markersByNodeId.set(node.id, marker);
                }
            });
            
            const avgAqi = aqiCount > 0 ? Math.round(totalAqi / aqiCount) : null;
            document.getElementById('mapActiveCount').textContent = activeCount;
            document.getElementById('mapOfflineCount').textContent = offlineCount;
            document.getElementById('mapAvgAqi').textContent = avgAqi !== null ? avgAqi : '—';
            
            const statusTag = document.getElementById('mapStatusTag');
            if (statusTag) {
                if (offlineCount > 0) {
                    statusTag.className = 'cd-time-tag ongoing';
                    statusTag.textContent = '⚠️ PARTIAL';
                } else {
                    statusTag.className = 'cd-time-tag stable';
                    statusTag.textContent = 'LIVE';
                }
            }
            
            // Select first node if none selected
            if (!selectedNodeId && nodes.length > 0) {
                selectNode(nodes[0].id);
            }
            
            console.log(`[Dashboard Map] Rendered: ${activeCount} active, ${offlineCount} offline`);
        }
        
        // Select and show node details in drilldown panel
        function selectNode(nodeId) {
            selectedNodeId = nodeId;
            const nodes = window.CDASHBOARD_NODES || [];
            const node = nodes.find(n => n.id == nodeId);
            
            if (!node) return;
            
            // Update drilldown panel
            document.getElementById('dd-node-name').textContent = node.name || 'Unknown Node';
            
            const isActive = node.status === 'active' || node.status === 'online';
            const statusClass = isActive ? 'cd-good' : 'cd-critical';
            const statusText = isActive ? 'ACTIVE' : 'OFFLINE';
            document.getElementById('dd-status').className = `cd-status-pill ${statusClass}`;
            document.getElementById('dd-status').textContent = statusText;
            
            document.getElementById('dd-meta').innerHTML = `<span>📍 ${node.location || 'Unknown location'}</span>`;
            document.getElementById('dd-aqi').innerHTML = node.aqi !== null ? Math.round(node.aqi) : '—';
            document.getElementById('dd-pm25').innerHTML = node.pm2_5 !== null ? Math.round(node.pm2_5) : '—';
            document.getElementById('dd-pm10').innerHTML = node.pm10 !== null ? Math.round(node.pm10) : '—';
            document.getElementById('dd-temp').innerHTML = node.temperature !== null ? Math.round(node.temperature) : '—';
            document.getElementById('dd-last-seen').innerHTML = `<span class="cd-activity-text">Last seen: ${formatRelativeTime(node.last_seen || node.timestamp)}</span>`;
            
            // Highlight selected marker
            markersByNodeId.forEach((marker, id) => {
                const div = marker._icon?.querySelector('.cd-dashboard-marker');
                if (div) {
                    if (id == nodeId) {
                        div.style.transform = 'scale(1.15)';
                        div.style.boxShadow = '0 0 0 4px rgba(0,0,0,0.2)';
                    } else {
                        div.style.transform = '';
                        div.style.boxShadow = '';
                    }
                }
            });
        }
        
        // Refresh data from API (like Map View)
        async function refreshFromApi() {
            const endpoint = timeframe === 'live' ? '/api/nodes/live/' : '/api/nodes/24h/';
            try {
                const response = await fetch(endpoint);
                if (response.ok) {
                    const data = await response.json();
                    const allNodes = [];
                    if (data.active) allNodes.push(...data.active);
                    if (data.inactive) allNodes.push(...data.inactive);
                    if (data.rogue) allNodes.push(...data.rogue);
                    
                    const formattedNodes = allNodes.map(item => ({
                        id: item.node.id,
                        name: item.node.name,
                        location: item.node.location,
                        latitude: item.node.latitude,
                        longitude: item.node.longitude,
                        status: item.node.status,
                        aqi: item.pollutants?.aqi,
                        pm2_5: item.pollutants?.pm25,
                        pm10: item.pollutants?.pm10,
                        temperature: item.pollutants?.temperature,
                        last_seen: item.latest_reading?.timestamp
                    }));
                    
                    window.CDASHBOARD_NODES = formattedNodes;
                    renderMarkers();
                }
            } catch(e) {
                console.warn('[Dashboard Map] API refresh failed:', e);
                renderMarkers();
            }
        }
        
        // Setup controls
        function setupControls() {
            const layerSelect = document.getElementById('cd-layer-select');
            if (layerSelect) {
                layerSelect.addEventListener('change', (e) => {
                    currentLayer = e.target.value;
                    renderMarkers();
                    // Update legend
                    const legend = document.getElementById('cd-map-legend');
                    if (legend) {
                        if (currentLayer === 'aqi') legend.innerHTML = '<span class="cd-legend-title">AQI</span><div class="cd-legend-item"><div class="cd-legend-color" style="background: #10b981;"></div> Good</div><div class="cd-legend-item"><div class="cd-legend-color" style="background: #f59e0b;"></div> Mod</div><div class="cd-legend-item"><div class="cd-legend-color" style="background: #f97316;"></div> Sens</div><div class="cd-legend-item"><div class="cd-legend-color" style="background: #ef4444;"></div> Unh</div><div class="cd-legend-item"><div class="cd-legend-color" style="background: #7f1d1d;"></div> Haz</div>';
                        else legend.innerHTML = `<span class="cd-legend-title">${layerSelect.options[layerSelect.selectedIndex].text}</span>`;
                    }
                });
            }
            
            const toggleActive = document.getElementById('cd-toggle-active');
            if (toggleActive) {
                toggleActive.addEventListener('click', () => {
                    overlays.active = !overlays.active;
                    toggleActive.classList.toggle('cd-off', !overlays.active);
                    renderMarkers();
                });
            }
            
            const toggleInactive = document.getElementById('cd-toggle-inactive');
            if (toggleInactive) {
                toggleInactive.addEventListener('click', () => {
                    overlays.inactive = !overlays.inactive;
                    toggleInactive.classList.toggle('cd-off', !overlays.inactive);
                    renderMarkers();
                });
            }
            
            const liveBtn = document.getElementById('cd-btn-live');
            const btn24h = document.getElementById('cd-btn-24h');
            
            if (liveBtn) {
                liveBtn.addEventListener('click', () => {
                    timeframe = 'live';
                    liveBtn.classList.add('cd-active');
                    btn24h.classList.remove('cd-active');
                    refreshFromApi();
                });
            }
            if (btn24h) {
                btn24h.addEventListener('click', () => {
                    timeframe = '24h';
                    btn24h.classList.add('cd-active');
                    liveBtn.classList.remove('cd-active');
                    refreshFromApi();
                });
            }
            
            const viewMapBtn = document.getElementById('dd-view-map');
            if (viewMapBtn) {
                viewMapBtn.addEventListener('click', () => {
                    window.location.href = '/dashboard/map/';
                });
            }
        }
        
        // Initialize
        function init() {
            if (typeof L === 'undefined') {
                console.error('[Dashboard Map] Leaflet not loaded');
                return;
            }
            initMap();
            setupControls();
            refreshFromApi();
        }
        
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', init);
        } else {
            init();
        }
    })();
    </script>
    
    <script src="{% static 'AppEnviroNode/js/dashboard-users-context.js' %}"></script>
{% endblock %}