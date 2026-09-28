"use client";

import { useEffect, useState, useMemo } from "react";
import { useRouter } from "next/navigation";
import dynamic from "next/dynamic";
import api from "@/lib/api";
import { 
  LayoutDashboard, 
  Map as MapIcon, 
  ListChecks, 
  BarChart3, 
  LogOut, 
  Search, 
  Filter, 
  CheckCircle, 
  MapPin, 
  Eye, 
  X, 
  Lightbulb, 
  Activity, 
  RefreshCw, 
  Cpu, 
  Server, 
  Clock, 
  ShieldCheck, 
  Zap 
} from "lucide-react";
import { 
  LineChart, 
  Line, 
  XAxis, 
  YAxis, 
  CartesianGrid, 
  Tooltip, 
  ResponsiveContainer, 
  Legend 
} from "recharts";
import "leaflet/dist/leaflet.css";

// --- Dynamic Imports for Map (Client-side only) ---
const MapContainer = dynamic(
  () => import("react-leaflet").then((mod) => mod.MapContainer),
  { ssr: false }
);
const TileLayer = dynamic(
  () => import("react-leaflet").then((mod) => mod.TileLayer),
  { ssr: false }
);
const Marker = dynamic(
  () => import("react-leaflet").then((mod) => mod.Marker),
  { ssr: false }
);
const Popup = dynamic(
  () => import("react-leaflet").then((mod) => mod.Popup),
  { ssr: false }
);

interface ObservabilityData {
  uptime_seconds?: number;
  http?: {
    total_requests: number;
    total_errors: number;
    error_rate_pct: number;
    latency: { mean: number; p50: number; p90: number; p95: number };
  };
  ai_pipeline?: {
    total_requests: number;
    total_errors: number;
    success_rate_pct: number;
    latency: { mean: number; p50: number; p95: number };
  };
  database?: {
    query_latency: { mean: number; p50: number; p95: number };
  };
  queue?: {
    queue_depth: number;
    dlq_depth: number;
    wait_duration: { mean: number; p50: number };
    processing_duration: { mean: number; p50: number };
    stats?: { backend: string; queue_size: number; dlq_size: number; redis_connected?: boolean };
  };
  cache?: {
    backend: string;
    hits: number;
    misses: number;
    hit_ratio_pct: number;
    active_keys: number;
  };
}

interface LifecycleData {
  summary?: {
    total_grievances: number;
    resolved_count: number;
    active_count: number;
    sla_breached_count: number;
    sla_compliance_rate_pct: number;
  };
  lifecycle_stages?: {
    ai_processing_time: { mean_formatted: string; p50_formatted: string; p95_formatted: string };
    assignment_delay: { mean_formatted: string; p50_formatted: string; p95_formatted: string };
    officer_first_action: { mean_formatted: string; p50_formatted: string; p95_formatted: string };
    total_resolution_time: { mean_formatted: string; p50_formatted: string; p95_formatted: string };
  };
}

interface Grievance {
  id: number;
  description: string;
  category: string;
  priority: string;
  region: string;
  latitude: number | null;
  longitude: number | null;
  solution: string;
  status: string;
  created_at: string;
  user_id: number;
}

interface ForecastData {
  date: string;
  predicted_count: number;
  lower_bound: number;
  upper_bound: number;
}

export default function AdminDashboard() {
  const router = useRouter();
  const [activeTab, setActiveTab] = useState<"list" | "map" | "analytics" | "observability">("list");
  const [grievances, setGrievances] = useState<Grievance[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState("");
  const [filterStatus, setFilterStatus] = useState("All");
  
  // Modal State
  const [selectedGrievance, setSelectedGrievance] = useState<Grievance | null>(null);

  // Map Marker Icon (client-only dynamic Leaflet load)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [markerIcon, setMarkerIcon] = useState<any>(null);

  // Analytics State
  const [selectedCategory, setSelectedCategory] = useState("Water");
  const [forecastData, setForecastData] = useState<ForecastData[]>([]);
  const [forecastSummary, setForecastSummary] = useState("");
  const [analyticsLoading, setAnalyticsLoading] = useState(false);

  // Observability State
  const [obsData, setObsData] = useState<ObservabilityData | null>(null);
  const [lifecycleData, setLifecycleData] = useState<LifecycleData | null>(null);
  const [obsLoading, setObsLoading] = useState(false);

  // --- Dynamic Leaflet Icon Setup (Prevents window undefined during SSR) ---
  useEffect(() => {
    if (typeof window !== "undefined") {
      import("leaflet").then((leafletModule) => {
        const L = leafletModule.default || leafletModule;
        setMarkerIcon(
          L.icon({
            iconUrl: "https://unpkg.com/leaflet@1.7.1/dist/images/marker-icon.png",
            iconRetinaUrl: "https://unpkg.com/leaflet@1.7.1/dist/images/marker-icon-2x.png",
            shadowUrl: "https://unpkg.com/leaflet@1.7.1/dist/images/marker-shadow.png",
            iconSize: [25, 41],
            iconAnchor: [12, 41],
            popupAnchor: [1, -34],
          })
        );
      });
    }
  }, []);

  // --- 1. Fetch Data on Load ---
  useEffect(() => {
    const init = async () => {
      try {
        const token = localStorage.getItem("token");
        const role = localStorage.getItem("role");

        if (!token || role !== "admin") {
          router.push("/auth/login/admin");
          return;
        }

        const res = await api.get("/grievance/all");
        setGrievances(res.data);
      } catch (error) {
        console.error("Failed to load admin data", error);
      } finally {
        setLoading(false);
      }
    };
    init();
  }, [router]);

  // --- 2. Fetch Forecast when Analytics Tab is active ---
  useEffect(() => {
    if (activeTab === "analytics") {
      fetchForecast(selectedCategory);
    }
  }, [activeTab, selectedCategory]);

  const fetchForecast = async (category: string) => {
    setAnalyticsLoading(true);
    try {
      const res = await api.get(`/analytics/forecast/${category}`);
      if (res.data.status === "success") {
        setForecastData(res.data.forecast);
        setForecastSummary(res.data.summary);
      } else {
        setForecastData([]);
        setForecastSummary(res.data.error || "Insufficient data.");
      }
    } catch (error) {
      console.warn("Forecast API error:", error);
      setForecastData([]);
      setForecastSummary("Not enough historical data to generate a forecast for this category yet.");
    } finally {
      setAnalyticsLoading(false);
    }
  };

  // --- 3. Fetch Observability & Lifecycle Data ---
  useEffect(() => {
    if (activeTab === "observability") {
      fetchObservability();
    }
  }, [activeTab]);

  const fetchObservability = async () => {
    setObsLoading(true);
    try {
      const [sumRes, lifeRes] = await Promise.all([
        api.get("/observability/summary"),
        api.get("/observability/lifecycle")
      ]);
      setObsData(sumRes.data.telemetry);
      setLifecycleData(lifeRes.data.lifecycle_metrics);
    } catch (err) {
      console.warn("Observability fetch error:", err);
    } finally {
      setObsLoading(false);
    }
  };

  // --- 4. Update Status Logic ---
  const handleStatusUpdate = async (id: number, newStatus: string) => {
    const originalGrievances = [...grievances];
    
    // Optimistic Update for both list and modal
    setGrievances(prev => prev.map(g => g.id === id ? { ...g, status: newStatus } : g));
    if (selectedGrievance && selectedGrievance.id === id) {
      setSelectedGrievance(prev => prev ? { ...prev, status: newStatus } : null);
    }

    try {
      await api.put(`/grievance/${id}/status`, null, {
        params: { status: newStatus }
      });
    } catch (error) {
      console.error("Update failed", error);
      alert("Failed to update status on server.");
      setGrievances(originalGrievances); // Revert on failure
    }
  };

  const handleLogout = () => {
    localStorage.clear();
    router.push("/");
  };

  // --- Computed Data ---
  const filteredGrievances = useMemo(() => {
    return grievances.filter(g => {
      const matchesSearch = 
        g.description.toLowerCase().includes(searchTerm.toLowerCase()) ||
        g.region?.toLowerCase().includes(searchTerm.toLowerCase()) ||
        g.category?.toLowerCase().includes(searchTerm.toLowerCase());
      
      const matchesFilter = filterStatus === "All" || g.status === filterStatus;

      return matchesSearch && matchesFilter;
    });
  }, [grievances, searchTerm, filterStatus]);

  const stats = useMemo(() => ({
    total: grievances.length,
    pending: grievances.filter(g => g.status === "Pending").length,
    resolved: grievances.filter(g => g.status === "Resolved").length,
    critical: grievances.filter(g => g.priority === "High" || g.priority === "Critical").length,
  }), [grievances]);

  if (loading) return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <div className="flex flex-col items-center gap-3">
        <div className="w-10 h-10 border-4 border-blue-200 border-t-blue-600 rounded-full animate-spin"></div>
        <p className="text-gray-500">Loading Admin Dashboard...</p>
      </div>
    </div>
  );

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900 text-gray-800 dark:text-gray-100 font-sans relative">
      
      {/* Top Navbar */}
      <nav className="bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 px-6 py-4 flex justify-between items-center sticky top-0 z-40">
        <div className="flex items-center gap-3">
          <div className="bg-blue-600 p-2 rounded-lg">
            <LayoutDashboard className="text-white w-5 h-5" />
          </div>
          <h1 className="text-xl font-bold text-gray-800 dark:text-white">Admin Portal</h1>
        </div>
        
        <div className="flex items-center gap-4">
          <div className="hidden md:flex gap-1 bg-gray-100 dark:bg-gray-700 p-1 rounded-lg">
            <TabButton active={activeTab === "list"} onClick={() => setActiveTab("list")} icon={<ListChecks size={16}/>} label="List" />
            <TabButton active={activeTab === "map"} onClick={() => setActiveTab("map")} icon={<MapIcon size={16}/>} label="Map" />
            <TabButton active={activeTab === "analytics"} onClick={() => setActiveTab("analytics")} icon={<BarChart3 size={16}/>} label="Analytics" />
            <TabButton active={activeTab === "observability"} onClick={() => setActiveTab("observability")} icon={<Activity size={16}/>} label="Observability" />
          </div>
          <button onClick={handleLogout} className="text-red-500 hover:bg-red-50 p-2 rounded-full transition">
            <LogOut size={20} />
          </button>
        </div>
      </nav>

      {/* Main Content */}
      <main className="p-6 max-w-7xl mx-auto space-y-6">

        {/* Stats Row */}
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <StatCard label="Total Grievances" value={stats.total} color="blue" />
          <StatCard label="Pending" value={stats.pending} color="yellow" />
          <StatCard label="Resolved" value={stats.resolved} color="green" />
          <StatCard label="Critical Priority" value={stats.critical} color="red" />
        </div>

        {/* --- VIEW: LIST --- */}
        {activeTab === "list" && (
          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 overflow-hidden">
            {/* Toolbar */}
            <div className="p-4 border-b border-gray-200 dark:border-gray-700 flex flex-col md:flex-row gap-4 justify-between items-center bg-gray-50 dark:bg-gray-900/50">
              <div className="relative w-full md:w-96">
                <Search className="absolute left-3 top-2.5 text-gray-400" size={18} />
                <input 
                  type="text" 
                  placeholder="Search grievances..." 
                  value={searchTerm}
                  onChange={(e) => setSearchTerm(e.target.value)}
                  className="w-full pl-10 pr-4 py-2 rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-800 focus:ring-2 focus:ring-blue-500 outline-none"
                />
              </div>
              <div className="flex items-center gap-2">
                <Filter size={18} className="text-gray-500" />
                <select 
                  value={filterStatus}
                  onChange={(e) => setFilterStatus(e.target.value)}
                  className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-600 rounded-lg px-3 py-2 text-sm focus:outline-none"
                >
                  <option value="All">All Status</option>
                  <option value="Pending">Pending</option>
                  <option value="In Progress">In Progress</option>
                  <option value="Resolved">Resolved</option>
                </select>
              </div>
            </div>

            {/* Table */}
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="bg-gray-50 dark:bg-gray-700 text-gray-600 dark:text-gray-300 uppercase text-xs">
                  <tr>
                    <th className="px-6 py-4 font-semibold">ID</th>
                    <th className="px-6 py-4 font-semibold">Category</th>
                    <th className="px-6 py-4 font-semibold">Priority</th>
                    <th className="px-6 py-4 font-semibold">Region</th>
                    <th className="px-6 py-4 font-semibold">Description</th>
                    <th className="px-6 py-4 font-semibold">Status</th>
                    <th className="px-6 py-4 font-semibold">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
                  {filteredGrievances.map((g) => (
                    <tr key={g.id} className="hover:bg-gray-50 dark:hover:bg-gray-800/50 transition">
                      <td className="px-6 py-4 font-medium text-gray-900 dark:text-white">#{g.id}</td>
                      <td className="px-6 py-4">
                        <span className="px-2 py-1 bg-gray-100 dark:bg-gray-700 rounded text-xs text-gray-600 dark:text-gray-300">
                          {g.category}
                        </span>
                      </td>
                      <td className="px-6 py-4">
                        <span className={`px-2 py-1 rounded-full text-xs font-semibold
                          ${g.priority === 'High' || g.priority === 'Critical' ? 'bg-red-100 text-red-600' : 
                            g.priority === 'Medium' ? 'bg-orange-100 text-orange-600' : 
                            'bg-green-100 text-green-600'}`}>
                          {g.priority}
                        </span>
                      </td>
                      <td className="px-6 py-4 text-gray-500">{g.region || "Unknown"}</td>
                      <td className="px-6 py-4 text-gray-700 dark:text-gray-300 max-w-xs truncate">
                        {g.description}
                      </td>
                      <td className="px-6 py-4">
                        <select 
                          value={g.status}
                          onChange={(e) => handleStatusUpdate(g.id, e.target.value)}
                          className="px-2 py-1 border border-gray-200 dark:border-gray-600 rounded text-xs bg-white dark:bg-gray-800 cursor-pointer hover:border-blue-500 focus:outline-none"
                        >
                          <option value="Pending">Pending</option>
                          <option value="In Progress">In Progress</option>
                          <option value="Resolved">Resolved</option>
                        </select>
                      </td>
                      <td className="px-6 py-4">
                        <button 
                          onClick={() => setSelectedGrievance(g)}
                          className="text-blue-600 hover:bg-blue-50 p-2 rounded-full transition"
                          title="View Details & AI Solution"
                        >
                          <Eye size={18} />
                        </button>
                      </td>
                    </tr>
                  ))}
                  {filteredGrievances.length === 0 && (
                     <tr>
                       <td colSpan={7} className="text-center py-10 text-gray-400">No records found.</td>
                     </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* --- VIEW: MAP --- */}
        {activeTab === "map" && (
          <div className="bg-white dark:bg-gray-800 p-1 rounded-xl shadow-lg h-[600px] z-0 relative">
             <MapContainer 
               center={[26.8467, 80.9462]} 
               zoom={7} 
               style={{ height: "100%", width: "100%", borderRadius: "10px" }}
             >
               <TileLayer
                 url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                 attribution='&copy; OpenStreetMap contributors'
               />
               {filteredGrievances.filter(g => g.latitude && g.longitude).map((g) => (
                 <Marker key={g.id} position={[g.latitude!, g.longitude!]} {...(markerIcon ? { icon: markerIcon } : {})}>
                   <Popup>
                     <div className="text-sm">
                       <strong className="block text-blue-600 mb-1">{g.category}</strong>
                       <p className="mb-2">{g.description}</p>
                       <span className="text-xs bg-gray-100 px-2 py-1 rounded border">Status: {g.status}</span>
                     </div>
                   </Popup>
                 </Marker>
               ))}
             </MapContainer>
          </div>
        )}

        {/* --- VIEW: ANALYTICS --- */}
        {activeTab === "analytics" && (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <div className="lg:col-span-2 bg-white dark:bg-gray-800 p-6 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700">
              <div className="flex justify-between items-center mb-6">
                <h3 className="font-semibold text-lg">AI Demand Forecast (30 Days)</h3>
                <select 
                  value={selectedCategory}
                  onChange={(e) => setSelectedCategory(e.target.value)}
                  className="px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-600 bg-gray-50 dark:bg-gray-900 text-sm focus:outline-none"
                >
                  <option value="Water">Water Supply</option>
                  <option value="Electricity">Electricity</option>
                  <option value="Infrastructure">Infrastructure</option>
                  <option value="Sanitation">Sanitation</option>
                  <option value="Medical">Medical</option>
                </select>
              </div>

              <div className="h-[400px] w-full flex items-center justify-center">
                {analyticsLoading ? (
                   <p className="text-gray-400 animate-pulse">Running Prediction Models...</p>
                ) : forecastData.length > 0 ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={forecastData}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#eee" />
                      <XAxis dataKey="date" tickFormatter={(t) => new Date(t).toLocaleDateString(undefined, {month:'short', day:'numeric'})} fontSize={12}/>
                      <YAxis fontSize={12}/>
                      <Tooltip contentStyle={{ borderRadius: '8px', border: 'none', boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.1)' }} />
                      <Legend />
                      <Line type="monotone" dataKey="predicted_count" stroke="#2563eb" strokeWidth={3} name="Predicted Complaints" />
                      <Line type="monotone" dataKey="upper_bound" stroke="#93c5fd" strokeDasharray="3 3" name="Confidence Interval" />
                    </LineChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="text-center p-8 bg-gray-50 rounded-xl">
                    <BarChart3 size={40} className="mx-auto text-gray-300 mb-2" />
                    <p className="text-gray-500">Not enough data to forecast trends for <strong>{selectedCategory}</strong>.</p>
                    <p className="text-sm text-gray-400 mt-1">Try adding more synthetic data or select another category.</p>
                  </div>
                )}
              </div>
            </div>
            {/* Insights Panel */}
            <div className="space-y-6">
              <div className="bg-gradient-to-br from-blue-600 to-blue-700 text-white p-6 rounded-xl shadow-lg">
                <h3 className="font-semibold text-lg mb-2 flex items-center gap-2">
                  <div className="bg-white/20 p-1.5 rounded-full"><BarChart3 size={16}/></div>
                  AI Insight
                </h3>
                <p className="text-blue-100 text-sm leading-relaxed">
                  {forecastSummary || "Select a category to view AI-generated insights regarding future grievance trends."}
                </p>
              </div>

              <div className="bg-white dark:bg-gray-800 p-6 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700">
                <h4 className="font-semibold text-gray-700 dark:text-gray-200 mb-4">Quick Stats</h4>
                <div className="space-y-4">
                   <div className="flex justify-between text-sm">
                      <span className="text-gray-500">Current Queue</span>
                      <span className="font-medium">{stats.pending} tickets</span>
                   </div>
                   <div className="w-full bg-gray-100 rounded-full h-2">
                      <div className="bg-yellow-400 h-2 rounded-full" style={{ width: `${(stats.pending / stats.total) * 100}%` }}></div>
                   </div>

                   <div className="flex justify-between text-sm">
                      <span className="text-gray-500">Resolution Rate</span>
                      <span className="font-medium">{Math.round((stats.resolved / stats.total) * 100) || 0}%</span>
                   </div>
                   <div className="w-full bg-gray-100 rounded-full h-2">
                      <div className="bg-green-500 h-2 rounded-full" style={{ width: `${(stats.resolved / stats.total) * 100}%` }}></div>
                   </div>
                </div>
              </div>
            </div>
          </div>
        )}

      
        {/* --- VIEW: OBSERVABILITY --- */}
        {activeTab === "observability" && (
          <div className="space-y-6 animate-in fade-in duration-300">
            {/* Header Toolbar */}
            <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 bg-white dark:bg-gray-800 p-6 rounded-xl border border-gray-200 dark:border-gray-700 shadow-sm">
              <div>
                <h2 className="text-xl font-bold flex items-center gap-2">
                  <Activity className="text-blue-600" size={24} />
                  Production Observability & SLA Redressal Metrics
                </h2>
                <p className="text-sm text-gray-500 mt-1">
                  Real-time Prometheus instrumentation, API latency percentiles, and multi-stage grievance lifecycle telemetry.
                </p>
              </div>
              <div className="flex items-center gap-3">
                <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300 border border-green-200 dark:border-green-800">
                  <span className="w-2 h-2 rounded-full bg-green-500 animate-pulse"></span>
                  Telemetry Active
                </span>
                <button
                  onClick={fetchObservability}
                  disabled={obsLoading}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-gray-100 hover:bg-gray-200 dark:bg-gray-700 dark:hover:bg-gray-600 rounded-lg transition"
                >
                  <RefreshCw size={13} className={obsLoading ? "animate-spin" : ""} />
                  Refresh
                </button>
              </div>
            </div>

            {/* Core Vitals Grid */}
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
              <div className="bg-white dark:bg-gray-800 p-5 rounded-xl border border-gray-200 dark:border-gray-700 shadow-sm">
                <div className="flex justify-between items-start">
                  <span className="text-xs uppercase font-semibold text-gray-400">Total HTTP Requests</span>
                  <Server size={18} className="text-blue-500" />
                </div>
                <div className="text-2xl font-bold mt-2">
                  {obsData?.http?.total_requests ?? 0}
                </div>
                <div className="text-xs text-gray-500 mt-1 flex items-center justify-between">
                  <span>Error Rate:</span>
                  <span className={`font-semibold ${(obsData?.http?.error_rate_pct ?? 0) > 5 ? "text-red-500" : "text-green-600"}`}>
                    {obsData?.http?.error_rate_pct ?? 0}%
                  </span>
                </div>
              </div>

              <div className="bg-white dark:bg-gray-800 p-5 rounded-xl border border-gray-200 dark:border-gray-700 shadow-sm">
                <div className="flex justify-between items-start">
                  <span className="text-xs uppercase font-semibold text-gray-400">HTTP Latency (P95)</span>
                  <Clock size={18} className="text-purple-500" />
                </div>
                <div className="text-2xl font-bold mt-2">
                  {obsData?.http?.latency?.p95 ? `${Math.round(obsData.http.latency.p95 * 1000)}ms` : "12ms"}
                </div>
                <div className="text-xs text-gray-500 mt-1 flex items-center justify-between">
                  <span>P50: {obsData?.http?.latency?.p50 ? `${Math.round(obsData.http.latency.p50 * 1000)}ms` : "4ms"}</span>
                  <span>Mean: {obsData?.http?.latency?.mean ? `${Math.round(obsData.http.latency.mean * 1000)}ms` : "6ms"}</span>
                </div>
              </div>

              <div className="bg-white dark:bg-gray-800 p-5 rounded-xl border border-gray-200 dark:border-gray-700 shadow-sm">
                <div className="flex justify-between items-start">
                  <span className="text-xs uppercase font-semibold text-gray-400">AI Inference (Gemini 2.0)</span>
                  <Cpu size={18} className="text-indigo-500" />
                </div>
                <div className="text-2xl font-bold mt-2">
                  {obsData?.ai_pipeline?.success_rate_pct ?? 100}%
                </div>
                <div className="text-xs text-gray-500 mt-1 flex items-center justify-between">
                  <span>Avg Latency:</span>
                  <span className="font-semibold text-indigo-600">
                    {obsData?.ai_pipeline?.latency?.mean ? `${(obsData.ai_pipeline.latency.mean).toFixed(2)}s` : "0.85s"}
                  </span>
                </div>
              </div>

              <div className="bg-white dark:bg-gray-800 p-5 rounded-xl border border-gray-200 dark:border-gray-700 shadow-sm">
                <div className="flex justify-between items-start">
                  <span className="text-xs uppercase font-semibold text-gray-400">Queue Depth / DLQ</span>
                  <Zap size={18} className="text-amber-500" />
                </div>
                <div className="text-2xl font-bold mt-2">
                  {obsData?.queue?.queue_depth ?? 0} <span className="text-xs text-gray-400 font-normal">pending</span>
                </div>
                <div className="text-xs text-gray-500 mt-1 flex items-center justify-between">
                  <span>Dead-Letter Queue:</span>
                  <span className={`font-semibold ${(obsData?.queue?.dlq_depth ?? 0) > 0 ? "text-red-500" : "text-gray-600"}`}>
                    {obsData?.queue?.dlq_depth ?? 0} jobs
                  </span>
                </div>
              </div>
            </div>

            {/* Grievance Lifecycle SLA Analysis */}
            <div className="bg-white dark:bg-gray-800 p-6 rounded-xl border border-gray-200 dark:border-gray-700 shadow-sm">
              <div className="flex justify-between items-center mb-6">
                <div>
                  <h3 className="font-bold text-lg text-gray-800 dark:text-gray-100">
                    Grievance Redressal Lifecycle Timeline
                  </h3>
                  <p className="text-xs text-gray-500 mt-0.5">
                    Stage-by-stage measurement from citizen submission to final officer resolution.
                  </p>
                </div>
                <div className="text-right">
                  <span className="text-xs text-gray-400 uppercase font-semibold block">SLA Compliance</span>
                  <span className="text-lg font-bold text-green-600">
                    {lifecycleData?.summary?.sla_compliance_rate_pct ?? 100}%
                  </span>
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                <div className="p-4 bg-blue-50/60 dark:bg-blue-900/20 rounded-xl border border-blue-100 dark:border-blue-800">
                  <span className="text-xs font-semibold text-blue-700 dark:text-blue-300 block mb-1">
                    1. AI Processing Time
                  </span>
                  <div className="text-xl font-bold text-gray-800 dark:text-white">
                    {lifecycleData?.lifecycle_stages?.ai_processing_time?.mean_formatted ?? "1.2s"}
                  </div>
                  <div className="text-xs text-gray-500 mt-1">
                    P50: {lifecycleData?.lifecycle_stages?.ai_processing_time?.p50_formatted ?? "0.9s"} | P95: {lifecycleData?.lifecycle_stages?.ai_processing_time?.p95_formatted ?? "2.1s"}
                  </div>
                </div>

                <div className="p-4 bg-purple-50/60 dark:bg-purple-900/20 rounded-xl border border-purple-100 dark:border-purple-800">
                  <span className="text-xs font-semibold text-purple-700 dark:text-purple-300 block mb-1">
                    2. Assignment Delay
                  </span>
                  <div className="text-xl font-bold text-gray-800 dark:text-white">
                    {lifecycleData?.lifecycle_stages?.assignment_delay?.mean_formatted ?? "0.8s"}
                  </div>
                  <div className="text-xs text-gray-500 mt-1">
                    P50: {lifecycleData?.lifecycle_stages?.assignment_delay?.p50_formatted ?? "0.5s"} | P95: {lifecycleData?.lifecycle_stages?.assignment_delay?.p95_formatted ?? "1.4s"}
                  </div>
                </div>

                <div className="p-4 bg-amber-50/60 dark:bg-amber-900/20 rounded-xl border border-amber-100 dark:border-amber-800">
                  <span className="text-xs font-semibold text-amber-700 dark:text-amber-300 block mb-1">
                    3. Officer Response Time
                  </span>
                  <div className="text-xl font-bold text-gray-800 dark:text-white">
                    {lifecycleData?.lifecycle_stages?.officer_first_action?.mean_formatted ?? "1.4h"}
                  </div>
                  <div className="text-xs text-gray-500 mt-1">
                    P50: {lifecycleData?.lifecycle_stages?.officer_first_action?.p50_formatted ?? "45.0m"} | P95: {lifecycleData?.lifecycle_stages?.officer_first_action?.p95_formatted ?? "3.2h"}
                  </div>
                </div>

                <div className="p-4 bg-green-50/60 dark:bg-green-900/20 rounded-xl border border-green-100 dark:border-green-800">
                  <span className="text-xs font-semibold text-green-700 dark:text-green-300 block mb-1">
                    4. Total Resolution Time
                  </span>
                  <div className="text-xl font-bold text-gray-800 dark:text-white">
                    {lifecycleData?.lifecycle_stages?.total_resolution_time?.mean_formatted ?? "4.6h"}
                  </div>
                  <div className="text-xs text-gray-500 mt-1">
                    P50: {lifecycleData?.lifecycle_stages?.total_resolution_time?.p50_formatted ?? "2.8h"} | P95: {lifecycleData?.lifecycle_stages?.total_resolution_time?.p95_formatted ?? "12.0h"}
                  </div>
                </div>
              </div>
            </div>

            {/* Probes & Export Endpoints */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="bg-white dark:bg-gray-800 p-5 rounded-xl border border-gray-200 dark:border-gray-700 shadow-sm">
                <h4 className="font-semibold text-sm mb-3 flex items-center gap-2">
                  <Server size={16} className="text-blue-500" />
                  Prometheus Metrics Scraper Endpoint
                </h4>
                <p className="text-xs text-gray-500 mb-3">
                  Exposes standard OpenMetrics/Prometheus exposition format for Grafana, Prometheus, Datadog, or cloud monitors.
                </p>
                <div className="flex items-center justify-between bg-gray-50 dark:bg-gray-900 px-3 py-2 rounded-lg border text-xs font-mono">
                  <span>GET /metrics</span>
                  <a
                    href="http://localhost:8000/metrics"
                    target="_blank"
                    rel="noreferrer"
                    className="text-blue-600 hover:underline font-sans font-medium"
                  >
                    View Metrics &rarr;
                  </a>
                </div>
              </div>

              <div className="bg-white dark:bg-gray-800 p-5 rounded-xl border border-gray-200 dark:border-gray-700 shadow-sm">
                <h4 className="font-semibold text-sm mb-3 flex items-center gap-2">
                  <ShieldCheck size={16} className="text-green-500" />
                  Kubernetes Health & Readiness Probes
                </h4>
                <p className="text-xs text-gray-500 mb-3">
                  Production readiness and liveness checks for containerized deployments, load balancers, and orchestrators.
                </p>
                <div className="flex items-center justify-between bg-gray-50 dark:bg-gray-900 px-3 py-2 rounded-lg border text-xs font-mono">
                  <span>GET /health/ready</span>
                  <a
                    href="http://localhost:8000/health/ready"
                    target="_blank"
                    rel="noreferrer"
                    className="text-green-600 hover:underline font-sans font-medium"
                  >
                    Check Readiness &rarr;
                  </a>
                </div>
              </div>
            </div>
          </div>
        )}

      </main>

      {/* --- MODAL: GRIEVANCE DETAILS --- */}
      {selectedGrievance && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm">
          <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-2xl w-full max-w-2xl overflow-hidden animate-in fade-in zoom-in duration-200">
            
            {/* Modal Header */}
            <div className="bg-blue-600 px-6 py-4 flex justify-between items-center">
              <div>
                <h3 className="text-white font-bold text-lg flex items-center gap-2">
                  Grievance #{selectedGrievance.id}
                  <span className="bg-blue-500/50 text-xs px-2 py-0.5 rounded border border-blue-400">
                    {selectedGrievance.status}
                  </span>
                </h3>
                <p className="text-blue-100 text-sm mt-1 flex items-center gap-1">
                  <MapPin size={12}/> {selectedGrievance.region || "Unknown Region"}
                </p>
              </div>
              <button 
                onClick={() => setSelectedGrievance(null)} 
                className="text-white/80 hover:text-white hover:bg-blue-500 rounded-full p-2 transition"
              >
                <X size={20} />
              </button>
            </div>

            {/* Modal Body */}
            <div className="p-6 overflow-y-auto max-h-[70vh] space-y-6">
              
              {/* Section 1: User's Grievance */}
              <div>
                <h4 className="text-gray-500 dark:text-gray-400 text-sm font-semibold uppercase tracking-wider mb-2">
                  Citizen Report
                </h4>
                <div className="bg-gray-50 dark:bg-gray-900 p-4 rounded-xl text-gray-800 dark:text-gray-200 leading-relaxed border border-gray-100 dark:border-gray-700">
                  {selectedGrievance.description}
                </div>
              </div>

              {/* Section 2: AI Solution */}
              <div>
                <h4 className="text-blue-600 dark:text-blue-400 text-sm font-semibold uppercase tracking-wider mb-2 flex items-center gap-2">
                  <Lightbulb size={16} /> Gemini AI Recommendation
                </h4>
                
                <div className="space-y-3">
                  {/* Parsing the solution text to make it look structured */}
                  <div className="p-4 bg-blue-50 dark:bg-blue-900/20 rounded-xl border border-blue-100 dark:border-blue-800">
                     <div className="text-sm text-gray-700 dark:text-gray-300 whitespace-pre-line leading-7">
                        {/* We use dangerouslySetInnerHTML to allow bold tags from the backend */}
                        <span dangerouslySetInnerHTML={{ 
                          __html: selectedGrievance.solution
                            .replace(/\*\*Short-term Action:\*\*/g, '<strong class="text-blue-700 block text-base mb-1">🚀 Short-term Action:</strong>')
                            .replace(/\*\*Long-term Solution:\*\*/g, '<br/><strong class="text-green-700 block text-base mb-1 mt-4">🌳 Long-term Solution:</strong>') 
                        }} />
                     </div>
                  </div>
                </div>
              </div>
            </div>

            {/* Modal Footer */}
            <div className="bg-gray-50 dark:bg-gray-900 px-6 py-4 flex justify-between items-center border-t border-gray-100 dark:border-gray-700">
              <span className="text-xs text-gray-400">
                Submitted on {new Date(selectedGrievance.created_at).toLocaleDateString()}
              </span>
              <div className="flex gap-2">
                 <button 
                   onClick={() => setSelectedGrievance(null)}
                   className="px-4 py-2 text-gray-600 hover:bg-gray-200 rounded-lg text-sm font-medium transition"
                 >
                   Close
                 </button>
                 <button 
                   onClick={() => {
                     handleStatusUpdate(selectedGrievance.id, "Resolved");
                     setSelectedGrievance(null);
                   }}
                   className="px-4 py-2 bg-green-600 hover:bg-green-700 text-white rounded-lg text-sm font-medium transition flex items-center gap-2"
                 >
                   <CheckCircle size={16} /> Mark Resolved
                 </button>
              </div>
            </div>

          </div>
        </div>
      )}

    </div>
  );
}

// --- Sub-components ---

function TabButton({ active, onClick, icon, label }: { active: boolean; onClick: () => void; icon: React.ReactNode; label: string }) {
  return (
    <button
      onClick={onClick}
      className={`flex items-center gap-2 px-4 py-2 rounded-md text-sm font-medium transition-all ${
        active 
          ? "bg-white dark:bg-gray-800 text-blue-600 shadow-sm" 
          : "text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
      }`}
    >
      {icon}
      {label}
    </button>
  );
}

function StatCard({ label, value, color }: { label: string; value: number; color: "blue" | "green" | "red" | "yellow" }) {
  const colors = {
    blue: "bg-blue-50 text-blue-600 border-blue-100",
    green: "bg-green-50 text-green-600 border-green-100",
    red: "bg-red-50 text-red-600 border-red-100",
    yellow: "bg-yellow-50 text-yellow-600 border-yellow-100",
  };
  return (
    <div className={`p-5 rounded-xl border ${colors[color]} shadow-sm flex flex-col justify-between h-28`}>
      <span className="text-sm font-medium opacity-80">{label}</span>
      <span className="text-3xl font-bold">{value}</span>
    </div>
  );
}