"use client";

import {
  createContext,
  useContext,
  useReducer,
  useCallback, // 👈 Added useCallback
  ReactNode,
} from "react";
import { apiFetch } from "@/app/lib/api";

// Update type definition to match your new multi-tenant organization structure
export type Business = {
  id: number;
  name: string;
  org_id: number;
  query_allocation?: number;
};

type State = {
  businesses: Business[];
  selectedBusiness: Business | null;
  isLoading: boolean;
};

type Action =
  | { type: "SET_BUSINESSES"; payload: Business[] }
  | { type: "SELECT_BUSINESS"; payload: Business | null } // Allowed null here for clearSelection
  | { type: "CLEAR_SELECTION" }
  | { type: "SET_LOADING"; payload: boolean };

const initialState: State = {
  businesses: [],
  selectedBusiness: null,
  isLoading: true,
};

function businessReducer(state: State, action: Action): State {
  switch (action.type) {
    case "SET_BUSINESSES": {
      const selectedBusiness = state.selectedBusiness
        ? action.payload.find((business) => business.id === state.selectedBusiness?.id) ?? null
        : null;
      return {
        ...state,
        businesses: action.payload,
        isLoading: false,
        // Never retain a selection that is absent from the latest authorized list.
        selectedBusiness: selectedBusiness ?? action.payload[0] ?? null,
      };
    }
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
  setBusinesses: (businesses: Business[]) => void; // 👈 Expose stable setter
  setIsLoading: (loading: boolean) => void;        // 👈 Expose stable setter
  refreshBusinesses: (orgIds: number[]) => Promise<Business[] | undefined>;
};

const BusinessContext = createContext<BusinessContextType | undefined>(undefined);

export function BusinessProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(businessReducer, initialState);

  // ✅ Stable Setter 1: Wrapped in useCallback to prevent reference changes
  const setBusinesses = useCallback((businesses: Business[]) => {
    dispatch({ type: "SET_BUSINESSES", payload: businesses });
  }, []);

  // ✅ Stable Setter 2: Wrapped in useCallback
  const setIsLoading = useCallback((loading: boolean) => {
    dispatch({ type: "SET_LOADING", payload: loading });
  }, []);

  // ✅ FIX: Wrapped in useCallback with an empty dependency array.
  // This guarantees its reference NEVER changes, breaking the infinite loop in your Gate's useEffect!
  const refreshBusinesses = useCallback(async (orgIds: number[]) => {
    if (!orgIds || orgIds.length === 0) {
      dispatch({ type: "SET_BUSINESSES", payload: [] });
      return [];
    }

    dispatch({ type: "SET_LOADING", payload: true });
    try {
      const res = await apiFetch("/me/businesses", {
        method: "POST",
        headers: { 
          "Content-Type": "application/json" 
        },
        body: JSON.stringify({
          org_ids: orgIds 
        }),
      });
  
      if (!res.ok) throw new Error("Could not reconcile business data.");
      
      const data = await res.json() as { businesses?: Business[] };
      const businessesList = data.businesses || [];
      
      dispatch({ type: "SET_BUSINESSES", payload: businessesList });
      return businessesList as Business[];
    } catch (err) {
      console.error("Multi-org fetch failed:", err);
      dispatch({ type: "SET_LOADING", payload: false });
    }
  }, []); // 👈 Keeps this function reference static across all renders

  const selectBusiness = useCallback((business: Business) => {
    dispatch({ type: "SELECT_BUSINESS", payload: business });
  }, []);

  const clearSelection = useCallback(() => {
    dispatch({ type: "CLEAR_SELECTION" });
  }, []);

  return (
    <BusinessContext.Provider
      value={{
        businesses: state.businesses,
        selectedBusiness: state.selectedBusiness,
        isLoading: state.isLoading,
        selectBusiness,
        clearSelection,
        setBusinesses,
        setIsLoading,
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
