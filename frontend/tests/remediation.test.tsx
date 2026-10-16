import { beforeEach, expect, test, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import axe from "axe-core";
import LoginPage from "../src/pages/LoginPage";
import ActivityPage from "../src/pages/ActivityPage";
import ApprovedWorkloadSummaryPage from "../src/pages/ApprovedWorkloadSummaryPage";

const api=vi.hoisted(()=>({getAccountStatus:vi.fn(),signIn:vi.fn(),saveSession:vi.fn(),setupAdmin:vi.fn(),getActivityPage:vi.fn(),downloadActivity:vi.fn(),getApprovedWorkloadSummary:vi.fn()}));
vi.mock("../src/api",()=>api);
beforeEach(()=>vi.resetAllMocks());

test("sign-in connection errors are announced, focused, and recoverable",async()=>{
  api.getAccountStatus.mockRejectedValueOnce(new Error("offline")).mockResolvedValue({setup_required:false});
  render(<MemoryRouter><LoginPage/></MemoryRouter>);
  const alert=await screen.findByRole("alert");
  await waitFor(()=>expect(document.activeElement).toBe(alert));
  fireEvent.click(screen.getByRole("button",{name:"Retry connection"}));
  await waitFor(()=>expect((screen.getByRole("button",{name:"Sign In"}) as HTMLButtonElement).disabled).toBe(false));
  expect(screen.queryByRole("alert")).toBeNull();
});

test("activity reaches older pages and applies date filters to export",async()=>{
  api.getActivityPage.mockResolvedValue({items:[],total:225,page:1,page_size:50});
  api.downloadActivity.mockResolvedValue(undefined);
  const {container}=render(<ActivityPage/>);
  await screen.findByText(/225 recorded actions/);
  fireEvent.click(screen.getByRole("button",{name:"Next"}));
  await waitFor(()=>expect(api.getActivityPage).toHaveBeenLastCalledWith({search:"",date_from:"",date_to:""},2));
  fireEvent.change(screen.getByLabelText("From"),{target:{value:"2020-01-01"}});
  fireEvent.change(screen.getByLabelText("Through"),{target:{value:"2020-01-31"}});
  fireEvent.click(screen.getByRole("button",{name:"Apply filters"}));
  await waitFor(()=>expect(api.getActivityPage).toHaveBeenLastCalledWith({search:"",date_from:"2020-01-01",date_to:"2020-01-31"},1));
  await waitFor(()=>expect((screen.getByRole("button",{name:"Export filtered history"}) as HTMLButtonElement).disabled).toBe(false));
  fireEvent.click(screen.getByRole("button",{name:"Export filtered history"}));
  expect(api.downloadActivity).toHaveBeenCalledWith({search:"",date_from:"2020-01-01",date_to:"2020-01-31"});
  const result=await axe.run(container,{runOnly:{type:"rule",values:["button-name","label","aria-valid-attr","aria-roles","td-headers-attr"]}});
  expect(result.violations).toEqual([]);
});

test("approved summary shows incomplete frozen costs instead of zero",async()=>{
  api.getApprovedWorkloadSummary.mockResolvedValue({workloads:1,weekly_hours:24,overload_hours:3,weekly_pay:100,term_pay:null,college_totals:[{college:"CAS",workloads:1,paid_hours:3,weekly_pay:100,term_pay:null}],allocation_warnings:[],items:[]});
  render(<MemoryRouter><ApprovedWorkloadSummaryPage/></MemoryRouter>);
  expect((await screen.findAllByText("Incomplete")).length).toBe(2);
});
