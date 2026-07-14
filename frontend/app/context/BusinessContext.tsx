"use client";

import {
  createContext,
  useContext,
  useReducer,
  useEffect,
  ReactNode,
} from "react";

// Update type definition to match your new multi-tenant organization structure
export type Business = {
  id: number;
  name: string;
  org_id: number; // Added org_id to match your backend payload
};

type State = {
  businesses: Business[];
  selectedBusiness: Business | null;
  isLoading: boolean;
};

type Action =
  | { type: "SET_BUSINESSES"; payload: Business[] }
  | { type: "SELECT_BUSINESS"; payload: Business }
  | { type: "CLEAR_SELECTION" }
  | { type: "SET_LOADING"; payload: boolean };

const initialState: State = {
  businesses: [],
  selectedBusiness: null,
  isLoading: true,
};

function businessReducer(state: State, action: Action): State {
  switch (action.type) {
    case "SET_BUSINESSES":
      return {
        ...state,
        businesses: action.payload,
        isLoading: false,
        selectedBusiness: state.selectedBusiness || action.payload[0] || null,
      };
    case "SELECT_BUSINESS":
      return { ...state, selectedBusiness: action.payload };
    case "CLEAR_SELECTION":
      return { ...state, selectedBusiness: null };
    case "SET_LOADING":
      return { ...state, isLoading: action.payload };
    default:
      return state;
  }
}

type BusinessContextType = {
  businesses: Business[];
  selectedBusiness: Business | null;
  isLoading: boolean;
  selectBusiness: (business: Business) => void;
  clearSelection: () => void;
  // ✅ FIX 1: Updated signature to accept orgIds array
  refreshBusinesses: (orgIds: number[]) => Promise<Business[] | undefined>;
};

const BusinessContext = createContext<BusinessContextType | undefined>(undefined);

export function BusinessProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(businessReducer, initialState);

  // Updated handler to correctly pass arrays to your POST endpoint
  const refreshBusinesses = async (orgIds: number[]) => {
    if (!orgIds || orgIds.length === 0) {
      dispatch({ type: "SET_BUSINESSES", payload: [] });
      return [];
    }

    dispatch({ type: "SET_LOADING", payload: true });
    try {
      const res = await fetch("http://localhost:8000/me/businesses", {
        method: "POST",
        credentials: "include",
        headers: { 
          "Content-Type": "application/json" 
        },
        body: JSON.stringify({
          org_ids: orgIds 
        }),
      });
  
      if (!res.ok) throw new Error("Could not reconcile business data.");
      
      const data = await res.json();
      
      // ✅ FIX 2: You forgot to dispatch the loaded businesses to your reducer!
      dispatch({ type: "SET_BUSINESSES", payload: data.businesses });
      return data.businesses as Business[];
    } catch (err) {
      console.error("Multi-org fetch failed:", err);
      dispatch({ type: "SET_LOADING", payload: false });
    }
  };

  // ✅ FIX 3: Removed the blank initial useEffect mount call because the context 
  // doesn't know *which* organization's businesses to grab until the user logs in 
  // or your AdminDashboard component triggers it with an active layout array context.

  const selectBusiness = (business: Business) => {
    dispatch({ type: "SELECT_BUSINESS", payload: business });
  };

  const clearSelection = () => {
    dispatch({ type: "CLEAR_SELECTION" });
  };

  return (
    <BusinessContext.Provider
      value={{
        businesses: state.businesses,
        selectedBusiness: state.selectedBusiness,
        isLoading: state.isLoading,
        selectBusiness,
        clearSelection,
        refreshBusinesses,
      }}
    >
      {children}
    </BusinessContext.Provider>
  );
}

export function useBusiness() {
  const context = useContext(BusinessContext);
  if (!context) {
    throw new Error("useBusiness must be used within BusinessProvider");
  }
  return context;
}