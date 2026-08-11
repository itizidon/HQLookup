"use client";

import {
  createContext,
  useCallback,
  useContext,
  useReducer,
  useRef,
  type ReactNode,
} from "react";
import { apiRequest } from "@/lib/api";

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
  | { type: "SELECT_BUSINESS"; payload: Business }
  | { type: "SET_LOADING"; payload: boolean }
  | { type: "RESET" };

const initialState: State = {
  businesses: [],
  selectedBusiness: null,
  isLoading: true,
};

function businessReducer(state: State, action: Action): State {
  switch (action.type) {
    case "SET_BUSINESSES": {
      const selectedBusiness = state.selectedBusiness
        ? action.payload.find(
            (business) => business.id === state.selectedBusiness?.id,
          ) ?? action.payload[0] ?? null
        : action.payload[0] ?? null;

      return {
        businesses: action.payload,
        selectedBusiness,
        isLoading: false,
      };
    }
    case "SELECT_BUSINESS":
      return state.businesses.some(
        (business) => business.id === action.payload.id,
      )
        ? { ...state, selectedBusiness: action.payload }
        : state;
    case "SET_LOADING":
      return { ...state, isLoading: action.payload };
    case "RESET":
      return { ...initialState, isLoading: false };
  }
}

type RefreshOptions = {
  signal?: AbortSignal;
};

type BusinessContextType = State & {
  selectBusiness: (business: Business) => void;
  resetBusinesses: () => void;
  refreshBusinesses: (
    orgIds: number[],
    options?: RefreshOptions,
  ) => Promise<Business[]>;
};

const BusinessContext = createContext<BusinessContextType | undefined>(undefined);

export function BusinessProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(businessReducer, initialState);
  const latestRequest = useRef(0);

  const refreshBusinesses = useCallback(
    async (orgIds: number[], options: RefreshOptions = {}) => {
      const requestId = ++latestRequest.current;
      const uniqueOrgIds = Array.from(new Set(orgIds)).filter(Number.isInteger);

      if (uniqueOrgIds.length === 0) {
        dispatch({ type: "SET_BUSINESSES", payload: [] });
        return [];
      }

      dispatch({ type: "SET_LOADING", payload: true });
      try {
        const data = await apiRequest<{ businesses?: Business[] }>(
          "/me/businesses",
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ org_ids: uniqueOrgIds }),
            signal: options.signal,
          },
        );
        const businesses = Array.isArray(data.businesses)
          ? data.businesses
          : [];

        if (requestId === latestRequest.current) {
          dispatch({ type: "SET_BUSINESSES", payload: businesses });
        }
        return businesses;
      } catch (error) {
        if (requestId === latestRequest.current) {
          dispatch({ type: "SET_LOADING", payload: false });
        }
        throw error;
      }
    },
    [],
  );

  const selectBusiness = useCallback((business: Business) => {
    dispatch({ type: "SELECT_BUSINESS", payload: business });
  }, []);

  const resetBusinesses = useCallback(() => {
    latestRequest.current += 1;
    dispatch({ type: "RESET" });
  }, []);

  return (
    <BusinessContext.Provider
      value={{
        ...state,
        selectBusiness,
        resetBusinesses,
        refreshBusinesses,
      }}
    >
      {children}
    </BusinessContext.Provider>
  );
}

export function useBusiness(): BusinessContextType {
  const context = useContext(BusinessContext);
  if (!context) {
    throw new Error("useBusiness must be used within BusinessProvider");
  }
  return context;
}
