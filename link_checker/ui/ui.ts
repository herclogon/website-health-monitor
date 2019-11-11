declare var rivets: any;
declare var $: any;
declare var Vue: any;

(async () => {
  let promise = fetch("/api/links/");
  const links = await (await promise).json();

  const app = new Vue({
    el: "#links",
    data: {
      links
    }
  });

  console.log(links);
})();
