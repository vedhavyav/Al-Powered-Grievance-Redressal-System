"use client";

import { useState, useRef, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Send, Bot, User } from "lucide-react"; // Make sure to install lucide-react if not present
import api from "@/lib/api";

interface ChatMessage {
  sender: "bot" | "user";
  text: string;
}

interface GrievanceAnalysis {
  category?: string;
  priority?: string;
  region?: string;
  solution?: string;
  original?: string;
  latitude?: number | null;
  longitude?: number | null;
  [key: string]: unknown;
}

export default function GrievanceChatbot({
  onSubmitted,
}: {
  onSubmitted: (g: GrievanceAnalysis | Record<string, unknown>) => void;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  
  const [chat, setChat] = useState<ChatMessage[]>([
    { sender: "bot", text: "Hello! I am your AI Grievance Assistant." },
    { sender: "bot", text: "Please describe the issue you are facing (e.g., 'Water supply broken in Kanpur')." },
  ]);

  const [description, setDescription] = useState("");
  const [step, setStep] = useState<"ask" | "confirm" | "done">("ask");
  const [analysis, setAnalysis] = useState<GrievanceAnalysis | null>(null);
  const [loading, setLoading] = useState(false);

  // Auto-scroll to bottom
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
    }
  }, [chat, loading]);

  const sendMessage = async () => {
    if (!description.trim()) return;

    // Add user's message
    setChat((prev) => [...prev, { sender: "user", text: description }]);
    const userText = description;
    setDescription("");

    // --- STEP 1: ANALYZE ---
    if (step === "ask") {
      setLoading(true);
      // Simulate a small delay for "thinking" feel
      setTimeout(() => {
        setChat((prev) => [...prev, { sender: "bot", text: "Analyzing your issue..." }]);
      }, 500);

      try {
        const res = await api.post("/ai/classify", { text: userText }); //
        const parsed = res.data;
        setAnalysis({ ...parsed, original: userText });

        setTimeout(() => {
            setChat((prev) => [
            ...prev,
            {
                sender: "bot",
                text: `I've detected the following:\n\n📂 **Category:** ${parsed.category}\n⚡ **Priority:** ${parsed.priority}\n📍 **Region:** ${parsed.region}`,
            },
            {
                sender: "bot",
                text: "Should I submit this grievance now? (Type **Yes** or **No**)",
            },
            ]);
            setStep("confirm");
            setLoading(false);
        }, 1500);

      } catch (e) {
        console.error("Chatbot Error:", e);
        setChat((prev) => [
          ...prev,
          { sender: "bot", text: "I couldn't analyze that. Could you try describing it differently?" },
        ]);
        setLoading(false);
      }
      return;
    }

    // --- STEP 2: CONFIRM ---
    if (step === "confirm") {
      if (description.toLowerCase().startsWith("y")) {
        setChat((prev) => [...prev, { sender: "bot", text: "Submitting your grievance..." }]);
        setLoading(true);

        try {
          const res = await api.post("/grievance/submit", {
            description: analysis?.original || description,
          });

          onSubmitted(res.data);

          setChat((prev) => [
            ...prev,
            { sender: "bot", text: "✅ **Success!** Your grievance has been submitted." },
            {
              sender: "bot",
              text: "You can see it in the list on the right. Would you like to report another issue?",
            },
          ]);
          setStep("ask");
        } catch (err) {
            console.error(err);
          setChat((prev) => [
            ...prev,
            { sender: "bot", text: "❌ Something went wrong while submitting. Please try again." },
          ]);
          setStep("ask");
        }
        setLoading(false);
      } else {
        setChat((prev) => [
          ...prev,
          { sender: "bot", text: "Okay, submission cancelled. Please describe the issue again." },
        ]);
        setStep("ask");
      }
    }
  };

  return (
    <div className="w-full bg-white dark:bg-gray-800 rounded-2xl shadow-xl border border-gray-100 dark:border-gray-700 h-[600px] flex flex-col overflow-hidden">
      
      {/* Header */}
      <div className="bg-blue-600 p-4 flex items-center gap-3 shadow-md">
        <div className="bg-white/20 p-2 rounded-full">
            <Bot className="text-white w-6 h-6" />
        </div>
        <div>
            <h3 className="text-white font-semibold text-lg">AI Assistant</h3>
            <p className="text-blue-100 text-xs">Powered by IGRS Team</p>
        </div>
      </div>

      {/* Chat Area */}
      <div 
        ref={scrollRef} 
        className="flex-1 overflow-y-auto p-4 space-y-4 bg-gray-50 dark:bg-gray-900 scroll-smooth"
      >
        <AnimatePresence>
            {chat.map((msg, index) => (
            <motion.div
                key={index}
                initial={{ opacity: 0, y: 10, scale: 0.95 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                transition={{ duration: 0.3 }}
                className={`flex gap-3 ${msg.sender === "user" ? "justify-end" : "justify-start"}`}
            >
                {msg.sender === "bot" && (
                    <div className="w-8 h-8 bg-blue-100 rounded-full flex items-center justify-center flex-shrink-0">
                        <Bot size={18} className="text-blue-600" />
                    </div>
                )}

                <div
                className={`max-w-[80%] px-5 py-3 rounded-2xl text-sm leading-relaxed shadow-sm ${
                    msg.sender === "bot"
                    ? "bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-200 border border-gray-200 dark:border-gray-700 rounded-tl-none"
                    : "bg-blue-600 text-white rounded-tr-none"
                }`}
                >
                <p dangerouslySetInnerHTML={{ 
                    __html: msg.text.replace(/\n/g, "<br/>").replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>') 
                }} />
                </div>

                {msg.sender === "user" && (
                    <div className="w-8 h-8 bg-blue-600 rounded-full flex items-center justify-center flex-shrink-0">
                        <User size={18} className="text-white" />
                    </div>
                )}
            </motion.div>
            ))}
        </AnimatePresence>

        {loading && (
          <motion.div 
            initial={{ opacity: 0 }} 
            animate={{ opacity: 1 }}
            className="flex gap-3 items-center"
          >
             <div className="w-8 h-8 bg-blue-100 rounded-full flex items-center justify-center">
                <Bot size={18} className="text-blue-600" />
            </div>
            <div className="bg-white dark:bg-gray-800 px-4 py-3 rounded-2xl rounded-tl-none border border-gray-200 dark:border-gray-700 flex gap-2">
                <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce"></span>
                <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce delay-100"></span>
                <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce delay-200"></span>
            </div>
          </motion.div>
        )}
      </div>

      {/* Input Section */}
      <div className="p-4 bg-white dark:bg-gray-800 border-t border-gray-100 dark:border-gray-700">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            sendMessage();
          }}
          className="flex gap-2 items-center"
        >
          <input
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            className="flex-1 bg-gray-100 dark:bg-gray-900 text-gray-800 dark:text-gray-100 px-4 py-3 rounded-xl border-none focus:ring-2 focus:ring-blue-500 outline-none transition-all placeholder-gray-400"
            placeholder="Type your message..."
            disabled={loading}
          />
          <button
            type="submit"
            disabled={loading || !description.trim()}
            className="p-3 bg-blue-600 text-white rounded-xl hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors shadow-lg shadow-blue-200 dark:shadow-none"
          >
            <Send size={20} />
          </button>
        </form>
      </div>
    </div>
  );
}