/** Runs before first paint (root layout <head>) so a male client never sees a
 *  pink flash, nor a female one a gold flash. Reads the persisted auth store. */
export const GENDER_THEME_SCRIPT = `try{var s=JSON.parse(localStorage.getItem("nb.auth")||"{}");var u=s&&s.state&&s.state.user;if(u&&u.gender==="FEMALE")document.documentElement.setAttribute("data-gender","FEMALE")}catch(e){}`;
